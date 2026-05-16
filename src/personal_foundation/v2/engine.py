"""Agent Runtime Engine — loads YAML agent definitions and executes them.

The single runtime that powers all agents. No per-agent Python files.
Agents are YAML config → the engine interprets them.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml
import instructor
from litellm import acompletion

from src.personal_foundation.v2.state import StateStore
from src.personal_foundation.v2.event_bus import EventBus
from src.personal_foundation.v2.policy import PolicyEngine, PolicyContext

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
AGENTS_DIR = REPO_ROOT / "agents"


class AgentEngine:
    """Loads YAML agent definitions and executes them against events.

    Each agent YAML defines:
    - trigger (event pattern)
    - model (litellm model string)
    - system_prompt
    - output_schema (Pydantic model name)
    - actions (conditional post-processing)
    - policy (which policy file governs this agent)
    """

    def __init__(
        self,
        store: StateStore,
        event_bus: EventBus,
        policy_engine: PolicyEngine,
        dry_run: bool = False,
    ) -> None:
        self.store = store
        self.bus = event_bus
        self.policy = policy_engine
        self.dry_run = dry_run
        self._agents: dict[str, dict] = {}
        self._semaphore = asyncio.Semaphore(3)  # Max 3 concurrent LLM calls

    def load_agents(self, agents_dir: Path | None = None) -> int:
        """Load all agent YAML definitions. Returns count loaded."""
        directory = agents_dir or AGENTS_DIR
        if not directory.exists():
            log.warning("AgentEngine: agents directory not found at %s", directory)
            return 0

        count = 0
        for yaml_file in sorted(directory.glob("*.yaml")):
            try:
                with yaml_file.open() as f:
                    data = yaml.safe_load(f)
                if data and "agent" in data:
                    agent_def = data["agent"]
                    name = agent_def["name"]
                    self._agents[name] = data
                    # Subscribe to trigger event
                    trigger = agent_def.get("trigger", "")
                    if trigger:
                        self.bus.subscribe(
                            trigger, name,
                            lambda event, agent_data=data: self._execute_agent(agent_data, event),
                        )
                    count += 1
                    log.info("AgentEngine: loaded agent '%s' (trigger: %s)", name, trigger)
            except Exception as exc:
                log.error("AgentEngine: failed to load %s: %s", yaml_file, exc)

        log.info("AgentEngine: %d agents loaded from %s", count, directory)
        return count

    async def _execute_agent(self, agent_data: dict, event: dict) -> None:
        """Execute an agent against an event."""
        agent_def = agent_data["agent"]
        agent_name = agent_def["name"]

        # Check if suspended
        if self.store.is_agent_suspended(agent_name):
            log.info("AgentEngine: %s is suspended, skipping", agent_name)
            return

        # Policy check: can this agent run?
        policy_ctx = PolicyContext(
            principal=agent_name,
            action="execute",
            resource_type="event",
            resource_id=event.get("event_type", ""),
            attributes=event.get("payload", {}),
        )
        decision = self.policy.evaluate(policy_ctx)
        if not decision.permitted:
            self.store.log_audit(
                agent=agent_name, action="blocked",
                status="denied", policy_result=f"{decision.rule_file}:{decision.rule_name}",
                result_summary=decision.reason,
            )
            return

        # Execute with concurrency limit
        async with self._semaphore:
            try:
                result = await self._call_llm(agent_def, event)
                await self._process_actions(agent_data, event, result)
                self.store.increment_agent_actions(agent_name, success=True)
                self.store.log_audit(
                    agent=agent_name, action=agent_def.get("trigger", "execute"),
                    status="success", model=agent_def.get("model", ""),
                    prompt_summary=f"Processed {event.get('event_type', '')}",
                    result_summary=str(result)[:200] if result else "",
                    dry_run=self.dry_run,
                    policy_result=f"{decision.rule_file}:{decision.rule_name}",
                )
            except Exception as exc:
                self.store.increment_agent_actions(agent_name, success=False)
                self.store.log_audit(
                    agent=agent_name, action=agent_def.get("trigger", "execute"),
                    status="failure", model=agent_def.get("model", ""),
                    result_summary=f"Error: {type(exc).__name__}: {str(exc)[:150]}",
                    dry_run=self.dry_run,
                )
                log.error("AgentEngine: %s failed: %s", agent_name, exc)

    async def _call_llm(self, agent_def: dict, event: dict) -> dict | str:
        """Call the LLM with the agent's system prompt and event data."""
        from src.personal_foundation.v2.cache import LLMCache
        from src.personal_foundation.v2.feedback import FeedbackStore
        from src.personal_foundation.v2.cost_tracker import CostTracker

        model = agent_def.get("model", "gpt-4o-mini")
        system_prompt = agent_def.get("system_prompt", "You are a helpful assistant.")
        temperature = agent_def.get("temperature", 0.3)
        max_tokens = agent_def.get("max_tokens", 1024)
        agent_name = agent_def.get("name", "unknown")

        # Build user message from event payload
        payload = event.get("payload", {})
        user_message = yaml.dump(payload, default_flow_style=False) if isinstance(payload, dict) else str(payload)

        if self.dry_run:
            log.info("[dry_run] AgentEngine: would call %s for %s", model, agent_name)
            return {"dry_run": True, "model": model, "agent": agent_name}

        # Check cache first
        cache = LLMCache(self.store)
        cached = cache.get(model, system_prompt, user_message)
        if cached:
            # Track as cached call (zero cost)
            cost_tracker = CostTracker(self.store)
            cost_tracker.record(agent_name, model, 0, 0, cached=True)
            return cached

        # Inject feedback context (few-shot learning from Bob's edits)
        feedback_store = FeedbackStore(self.store)
        feedback_context = feedback_store.build_few_shot_context(agent_name)
        if feedback_context:
            system_prompt = system_prompt + feedback_context

        # Call LLM
        response = await acompletion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        result = response.choices[0].message.content

        # Cache the response
        cache.put(model, agent_def.get("system_prompt", ""), user_message, result)

        # Track cost
        usage = response.usage
        if usage:
            cost_tracker = CostTracker(self.store)
            cost_tracker.record(agent_name, model, usage.prompt_tokens, usage.completion_tokens)

        return result

    async def _process_actions(self, agent_data: dict, event: dict, result: Any) -> None:
        """Process the agent's action rules against the LLM output."""
        actions = agent_data.get("actions", [])
        agent_name = agent_data["agent"]["name"]

        for action_def in actions:
            condition = action_def.get("when", "true")
            # Simple condition evaluation (safe subset)
            if not self._evaluate_condition(condition, result, event):
                continue

            do = action_def.get("do", "")
            params = action_def.get("params", {})

            # Policy check for the specific action
            policy_ctx = PolicyContext(
                principal=agent_name,
                action=do,
                resource_type=params.get("resource_type", "unknown"),
                resource_id=params.get("resource_id", ""),
                attributes=params,
            )
            decision = self.policy.evaluate(policy_ctx)
            if not decision.permitted:
                self.store.log_audit(
                    agent=agent_name, action=f"action_blocked:{do}",
                    status="denied", policy_result=f"{decision.rule_file}:{decision.rule_name}",
                    result_summary=decision.reason,
                )
                continue

            # Execute the action
            await self._execute_action(agent_name, do, params, result, event)

    async def _execute_action(
        self, agent_name: str, action: str, params: dict, result: Any, event: dict
    ) -> None:
        """Execute a single action."""
        if action == "queue_approval":
            self.store.enqueue_approval(
                agent=agent_name,
                action_type=params.get("type", "unknown"),
                description=params.get("description", str(result)[:200]),
                draft_content=str(result) if isinstance(result, str) else str(result),
                rationale=params.get("rationale", ""),
            )
        elif action == "emit_event":
            event_name = params.get("event", "agent.output")
            self.bus.emit(event_name, {"source_agent": agent_name, "result": result})
        elif action == "send_notification":
            # Handled by interface layer (Telegram, web push, etc.)
            self.bus.emit("notification.send", {
                "agent": agent_name,
                "message": params.get("message", str(result)[:500]),
                "urgency": params.get("urgency", "normal"),
            })
        elif action == "call_integration":
            if self.dry_run:
                log.info("[dry_run] Would call integration: %s.%s", params.get("name"), params.get("method"))
            else:
                # Dispatch to integration layer
                self.bus.emit("integration.call", {
                    "agent": agent_name,
                    "integration": params.get("name"),
                    "method": params.get("method"),
                    "params": params,
                })
        elif action == "log_audit":
            self.store.log_audit(
                agent=agent_name, action="custom_log",
                result_summary=params.get("summary", str(result)[:200]),
            )

    def _evaluate_condition(self, condition: str, result: Any, event: dict) -> bool:
        """Evaluate a simple condition string. Safe subset only."""
        if condition == "true":
            return True
        if condition == "false":
            return False
        # Simple attribute checks
        try:
            if "output." in condition and isinstance(result, dict):
                # e.g., "output.category == 'action-required'"
                parts = condition.split("==")
                if len(parts) == 2:
                    key = parts[0].strip().replace("output.", "")
                    value = parts[1].strip().strip("'\"")
                    return str(result.get(key, "")) == value
            if "output.confidence" in condition and isinstance(result, dict):
                if ">=" in condition:
                    threshold = float(condition.split(">=")[1].strip())
                    return float(result.get("confidence", 0)) >= threshold
                if "<" in condition:
                    threshold = float(condition.split("<")[1].strip())
                    return float(result.get("confidence", 0)) < threshold
        except (ValueError, KeyError, IndexError):
            pass
        return True  # Default: execute action
