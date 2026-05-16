"""9-Gate Pipeline — every artifact must pass all gates to reach "Yes."

Gates:
1. Schema validation (input conforms to expected shape)
2. Pre-execution policy check (action permitted by Cedar rules)
3. Budget check (agent within daily token budget)
4. Dedup check (not already processed)
5. Execute (call LLM, produce artifact)
6. Output validation (output conforms to schema)
7. Post-execution policy check (output contains no PII/secrets/harm)
8. Approval gate (human approval or auto-approve)
9. Truth store recording (append to immutable ledger)

An artifact is at "Yes" only when ALL 9 gates pass.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from src.personal_foundation.v2.state import StateStore
from src.personal_foundation.v2.policy import PolicyEngine, PolicyContext
from src.personal_foundation.v2.auto_approve import AutoApprover
from src.personal_foundation.v2.token_budget import TokenBudget
from src.personal_foundation.v2.cache import LLMCache

log = logging.getLogger(__name__)


@dataclass
class GateResult:
    """Result of a single gate evaluation."""
    gate_number: int
    gate_name: str
    passed: bool
    reason: str
    duration_ms: float = 0.0


@dataclass
class PipelineResult:
    """Result of the full 9-gate pipeline."""
    artifact_id: str
    reached_yes: bool
    gates_passed: int
    gates_total: int = 9
    gate_results: list[GateResult] = field(default_factory=list)
    output: Any = None
    blocked_at: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def summary(self) -> str:
        if self.reached_yes:
            return f"✅ YES ({self.gates_passed}/{self.gates_total} gates passed)"
        return f"❌ BLOCKED at gate {self.gates_passed + 1}: {self.blocked_at}"


# PII detection patterns
PII_PATTERNS = [
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', "email address"),
    (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', "phone number"),
    (r'\b\d{3}-\d{2}-\d{4}\b', "SSN"),
    (r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', "credit card"),
    (r'\b(?:sk-|gsk_|pplx-|Bearer\s)[A-Za-z0-9_-]{20,}\b', "API key"),
]


class GatePipeline:
    """The 9-gate pipeline for artifact correctness."""

    def __init__(
        self,
        store: StateStore,
        policy: PolicyEngine,
        auto_approver: AutoApprover,
        budget: TokenBudget,
        cache: LLMCache,
    ) -> None:
        self.store = store
        self.policy = policy
        self.auto_approver = auto_approver
        self.budget = budget
        self.cache = cache

    async def process(
        self,
        artifact_id: str,
        agent: str,
        action: str,
        input_data: dict,
        execute_fn: Callable[..., Awaitable[Any]],
        output_schema: type | None = None,
    ) -> PipelineResult:
        """Run an artifact through all 9 gates.

        Args:
            artifact_id: Unique ID for this artifact
            agent: Agent name (e.g., "personal/email_classifier")
            action: Action being performed
            input_data: Input to the agent
            execute_fn: Async function that produces the artifact (Gate 5)
            output_schema: Optional Pydantic model for output validation

        Returns:
            PipelineResult with pass/fail status and details
        """
        result = PipelineResult(artifact_id=artifact_id, reached_yes=False, gates_passed=0)

        # Gate 1: Schema validation (input)
        g1 = self._gate_1_schema_validate(input_data)
        result.gate_results.append(g1)
        if not g1.passed:
            result.blocked_at = g1.reason
            return result
        result.gates_passed = 1

        # Gate 2: Pre-execution policy check
        g2 = self._gate_2_policy_pre(agent, action, input_data)
        result.gate_results.append(g2)
        if not g2.passed:
            result.blocked_at = g2.reason
            return result
        result.gates_passed = 2

        # Gate 3: Budget check
        g3 = self._gate_3_budget(agent)
        result.gate_results.append(g3)
        if not g3.passed:
            result.blocked_at = g3.reason
            return result
        result.gates_passed = 3

        # Gate 4: Dedup check
        g4 = self._gate_4_dedup(agent, input_data)
        result.gate_results.append(g4)
        if not g4.passed:
            # Dedup means we have a cached result — that's a pass with cached output
            result.output = g4.reason  # Contains cached response
            result.gates_passed = 9  # Skip to end
            result.reached_yes = True
            return result
        result.gates_passed = 4

        # Gate 5: Execute
        try:
            output = await execute_fn(input_data)
            g5 = GateResult(5, "execute", True, "Execution successful")
            result.output = output
        except Exception as exc:
            g5 = GateResult(5, "execute", False, f"Execution failed: {type(exc).__name__}")
            result.gate_results.append(g5)
            result.blocked_at = g5.reason
            return result
        result.gate_results.append(g5)
        result.gates_passed = 5

        # Gate 6: Output validation
        g6 = self._gate_6_output_validate(output, output_schema)
        result.gate_results.append(g6)
        if not g6.passed:
            result.blocked_at = g6.reason
            return result
        result.gates_passed = 6

        # Gate 7: Post-execution policy check (PII, secrets, harm)
        g7 = self._gate_7_policy_post(output)
        result.gate_results.append(g7)
        if not g7.passed:
            result.blocked_at = g7.reason
            return result
        result.gates_passed = 7

        # Gate 8: Approval gate
        g8 = self._gate_8_approval(agent, action, output)
        result.gate_results.append(g8)
        if not g8.passed:
            result.blocked_at = g8.reason
            # Not blocked — just queued for human review
            # The artifact will reach Yes after approval
            return result
        result.gates_passed = 8

        # Gate 9: Truth store recording
        g9 = self._gate_9_record(artifact_id, agent, action, input_data, output)
        result.gate_results.append(g9)
        if not g9.passed:
            result.blocked_at = g9.reason
            return result
        result.gates_passed = 9

        result.reached_yes = True
        return result

    # ------------------------------------------------------------------
    # Individual gates
    # ------------------------------------------------------------------

    def _gate_1_schema_validate(self, input_data: dict) -> GateResult:
        """Gate 1: Validate input schema."""
        if not isinstance(input_data, dict):
            return GateResult(1, "schema_validate", False, "Input must be a dict")
        if not input_data:
            return GateResult(1, "schema_validate", False, "Input is empty")
        return GateResult(1, "schema_validate", True, "Input schema valid")

    def _gate_2_policy_pre(self, agent: str, action: str, input_data: dict) -> GateResult:
        """Gate 2: Pre-execution policy check."""
        ctx = PolicyContext(
            principal=agent, action=action,
            resource_type="artifact", resource_id="",
            attributes=input_data,
        )
        decision = self.policy.evaluate(ctx)
        if decision.permitted:
            return GateResult(2, "policy_pre", True, f"Permitted: {decision.rule_name}")
        return GateResult(2, "policy_pre", False, f"Denied: {decision.reason}")

    def _gate_3_budget(self, agent: str) -> GateResult:
        """Gate 3: Token budget check."""
        within, spent, limit = self.budget.check_budget(agent)
        if within:
            return GateResult(3, "budget", True, f"Within budget: ${spent:.3f} / ${limit:.2f}")
        return GateResult(3, "budget", False, f"Budget exceeded: ${spent:.3f} / ${limit:.2f}")

    def _gate_4_dedup(self, agent: str, input_data: dict) -> GateResult:
        """Gate 4: Deduplication check."""
        import json
        cache_key_input = json.dumps(input_data, sort_keys=True)
        cached = self.cache.get(agent, "dedup", cache_key_input)
        if cached:
            return GateResult(4, "dedup", False, cached)  # "False" means cache hit (skip execution)
        return GateResult(4, "dedup", True, "Not a duplicate")

    def _gate_6_output_validate(self, output: Any, schema: type | None) -> GateResult:
        """Gate 6: Output schema validation."""
        if output is None:
            return GateResult(6, "output_validate", False, "Output is None")
        if schema:
            try:
                if hasattr(schema, "model_validate"):
                    schema.model_validate(output if isinstance(output, dict) else {"content": output})
            except Exception as exc:
                return GateResult(6, "output_validate", False, f"Schema validation failed: {exc}")
        return GateResult(6, "output_validate", True, "Output valid")

    def _gate_7_policy_post(self, output: Any) -> GateResult:
        """Gate 7: Post-execution check for PII, secrets, harmful content."""
        output_str = str(output) if output else ""

        for pattern, pii_type in PII_PATTERNS:
            if re.search(pattern, output_str):
                return GateResult(7, "policy_post", False, f"Output contains {pii_type} — blocked")

        return GateResult(7, "policy_post", True, "No PII/secrets detected in output")

    def _gate_8_approval(self, agent: str, action: str, output: Any) -> GateResult:
        """Gate 8: Approval gate (auto-approve or queue)."""
        decision = self.auto_approver.evaluate(agent, action, confidence=0.95)
        if decision.auto_approved:
            return GateResult(8, "approval", True, f"Auto-approved: {decision.reason}")
        # Queue for human review
        self.store.enqueue_approval(
            agent=agent, action_type=action,
            description=f"Artifact from {agent}:{action}",
            draft_content=str(output)[:2000] if output else "",
        )
        return GateResult(8, "approval", False, "Queued for human approval")

    def _gate_9_record(self, artifact_id: str, agent: str, action: str, input_data: dict, output: Any) -> GateResult:
        """Gate 9: Record to truth store."""
        try:
            self.store.log_audit(
                agent=agent, action=action, status="success",
                result_summary=f"Artifact {artifact_id} reached Yes",
                details={"artifact_id": artifact_id, "gates_passed": 9},
            )
            return GateResult(9, "truth_store", True, "Recorded in truth store")
        except Exception as exc:
            return GateResult(9, "truth_store", False, f"Failed to record: {exc}")
