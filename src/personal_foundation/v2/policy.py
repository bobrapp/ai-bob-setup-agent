"""Policy engine — evaluates Cedar-style rules before agent actions.

Simplified Cedar implementation for the v2 system. Evaluates permit/forbid
rules from YAML policy files (Cedar syntax is complex to parse; we use a
simplified YAML representation that maps to the same semantics).

Every action is checked: PERMIT or DENY. Denied actions are logged and blocked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
POLICIES_DIR = REPO_ROOT / "policies"


@dataclass
class PolicyDecision:
    """Result of a policy evaluation."""
    permitted: bool
    rule_file: str
    rule_name: str
    reason: str


@dataclass
class PolicyContext:
    """Context for policy evaluation."""
    principal: str      # Agent name or operator name
    action: str         # What they're trying to do
    resource_type: str  # What they're acting on
    resource_id: str    # Specific resource
    attributes: dict    # Additional context


class PolicyEngine:
    """Evaluates policies from YAML files in the policies/ directory.

    Policy file format:
    ```yaml
    rules:
      - name: "moderator_cannot_delete"
        effect: "forbid"
        principal: "foundation/moderator"
        actions: ["delete_post", "hide_post"]
        resource_type: "circle_post"
        reason: "Moderator can never auto-remove content"

      - name: "welcomer_can_dm"
        effect: "permit"
        principal: "foundation/welcomer"
        actions: ["send_dm"]
        resource_type: "circle_member"
        conditions:
          is_new_member: true
    ```
    """

    def __init__(self, policies_dir: Path | None = None) -> None:
        self.policies_dir = policies_dir or POLICIES_DIR
        self._rules: list[dict] = []
        self._load_policies()

    def _load_policies(self) -> None:
        """Load all policy YAML files."""
        self._rules = []
        if not self.policies_dir.exists():
            log.warning("PolicyEngine: policies directory not found at %s", self.policies_dir)
            return

        for policy_file in sorted(self.policies_dir.rglob("*.yaml")):
            try:
                with policy_file.open() as f:
                    data = yaml.safe_load(f)
                if data and "rules" in data:
                    for rule in data["rules"]:
                        rule["_file"] = str(policy_file.relative_to(self.policies_dir))
                        self._rules.append(rule)
            except Exception as exc:
                log.error("PolicyEngine: failed to load %s: %s", policy_file, exc)

        log.info("PolicyEngine: loaded %d rules from %s", len(self._rules), self.policies_dir)

    def reload(self) -> None:
        """Reload policies from disk (hot-reload support)."""
        self._load_policies()

    def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        """Evaluate a policy context against all rules.

        Logic:
        1. Check all FORBID rules first — if any match, DENY
        2. Check all PERMIT rules — if any match, PERMIT
        3. Default: PERMIT (open by default, restrict explicitly)
        """
        # Check forbid rules first
        for rule in self._rules:
            if rule.get("effect") != "forbid":
                continue
            if self._rule_matches(rule, ctx):
                decision = PolicyDecision(
                    permitted=False,
                    rule_file=rule.get("_file", "unknown"),
                    rule_name=rule.get("name", "unnamed"),
                    reason=rule.get("reason", "Forbidden by policy"),
                )
                log.info("PolicyEngine: DENY %s.%s by rule '%s'",
                         ctx.principal, ctx.action, rule.get("name"))
                return decision

        # Check permit rules
        for rule in self._rules:
            if rule.get("effect") != "permit":
                continue
            if self._rule_matches(rule, ctx):
                return PolicyDecision(
                    permitted=True,
                    rule_file=rule.get("_file", "unknown"),
                    rule_name=rule.get("name", "unnamed"),
                    reason=rule.get("reason", "Permitted by policy"),
                )

        # Default: permit (open by default)
        return PolicyDecision(
            permitted=True,
            rule_file="default",
            rule_name="default_permit",
            reason="No matching forbid rule; default permit",
        )

    def _rule_matches(self, rule: dict, ctx: PolicyContext) -> bool:
        """Check if a rule matches the given context."""
        # Check principal
        principal_pattern = rule.get("principal", "*")
        if principal_pattern != "*" and principal_pattern != ctx.principal:
            # Support prefix matching (e.g., "foundation/*" matches "foundation/moderator")
            if not (principal_pattern.endswith("*") and
                    ctx.principal.startswith(principal_pattern[:-1])):
                return False

        # Check action
        actions = rule.get("actions", ["*"])
        if "*" not in actions and ctx.action not in actions:
            return False

        # Check resource type
        resource_type = rule.get("resource_type", "*")
        if resource_type != "*" and resource_type != ctx.resource_type:
            return False

        # Check conditions (if any)
        conditions = rule.get("conditions", {})
        for key, expected in conditions.items():
            actual = ctx.attributes.get(key)
            if actual != expected:
                return False

        return True
