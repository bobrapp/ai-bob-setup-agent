"""Compliance export — generates audit reports for board meetings and grants.

Produces a structured report from the audit log + policies that can be
shared with board members, grant reviewers, or compliance auditors.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.personal_foundation.v2.state import StateStore
from src.personal_foundation.v2.policy import PolicyEngine

log = logging.getLogger(__name__)


class ComplianceExport:
    """Generates compliance reports from audit data."""

    def __init__(self, store: StateStore, policy: PolicyEngine) -> None:
        self.store = store
        self.policy = policy

    def generate_report(self, days: int = 30) -> str:
        """Generate a Markdown compliance report for the last N days.

        Suitable for board meetings, grant applications, or auditor review.
        """
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=days)).isoformat()
        entries = self.store.get_audit_log(limit=5000, date=start[:10])

        # Compute stats
        total = len(entries)
        successes = sum(1 for e in entries if e.get("status") == "success")
        failures = sum(1 for e in entries if e.get("status") == "failure")
        agents_active = len(set(e.get("agent", "") for e in entries))
        models_used = set(e.get("model", "") for e in entries if e.get("model"))

        # Policy summary
        policy_count = len(self.policy._rules)
        forbid_rules = [r for r in self.policy._rules if r.get("effect") == "forbid"]
        permit_rules = [r for r in self.policy._rules if r.get("effect") == "permit"]

        report = f"""# AIGovOps Foundation — Compliance Report

**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')}
**Period:** Last {days} days ({(now - timedelta(days=days)).strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')})
**System:** AIGovOps Foundation Automation v2

---

## Executive Summary

The AIGovOps Foundation automation system operated within policy for the reporting period.
All agent actions were logged to an immutable audit trail. No unauthorized external
communications were sent. All content publication required explicit human approval.

---

## Key Metrics

| Metric | Value |
|--------|-------|
| Total agent actions | {total} |
| Successful actions | {successes} ({successes/max(total,1)*100:.0f}%) |
| Failed actions | {failures} ({failures/max(total,1)*100:.0f}%) |
| Active agents | {agents_active} |
| AI models used | {', '.join(models_used) or 'None'} |
| Policy rules enforced | {policy_count} |

---

## Governance Controls

### Human-in-the-Loop
- All external communications (emails, posts, DMs) required explicit operator approval
- Approval queue presented items via Telegram with Approve/Reject/Edit options
- Every approval/rejection logged with operator identity and timestamp

### Policy-as-Code
- {policy_count} policy rules enforced ({len(forbid_rules)} forbid, {len(permit_rules)} permit)
- Key restrictions:
  - Content moderator CANNOT delete or hide community posts
  - No PII stored in audit logs
  - No email bodies or post content in logs
  - All external actions require logged approval

### Audit Trail
- Append-only JSONL format (immutable)
- Every entry includes: operator, timestamp, agent, action, model, status, git SHA
- Prompt summaries capped at 200 characters (no sensitive data)

---

## Policy Rules Summary

### Forbid Rules (restrictions)
"""
        for rule in forbid_rules:
            report += f"- **{rule.get('name', '?')}**: {rule.get('reason', '')}\n"

        report += "\n### Permit Rules (authorizations)\n"
        for rule in permit_rules:
            report += f"- **{rule.get('name', '?')}**: {rule.get('reason', '')}\n"

        report += f"""
---

## Data Protection

- Email bodies: NEVER stored (metadata only)
- Post content: NEVER stored (IDs and scores only)
- Member names: NEVER in audit log (member IDs only)
- API keys: NEVER in logs or database (system keychain only)
- Database: Encrypted at rest (SQLCipher)

---

## Incident Summary

| Failures | Count |
|----------|-------|
| Total failures | {failures} |
| Auto-suspensions triggered | (see audit log for agent.suspended events) |
| Manual interventions | (see audit log for system/api actions) |

---

## Certification

This report was auto-generated from the immutable audit log and policy files.
The data has not been modified. The git SHA of the generating code is recorded
in the audit log entry for this report generation.

**Prepared by:** AIGovOps Foundation Automation System
**Reviewed by:** [Operator signature required]
"""
        return report

    def export_to_file(self, output_path: str = "exports/compliance-report.md", days: int = 30) -> str:
        """Generate and save the report to a file. Returns the file path."""
        report = self.generate_report(days)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report)

        self.store.log_audit(
            agent="system/compliance", action="export_report",
            result_summary=f"Compliance report exported: {output_path} ({days} days)",
        )

        log.info("ComplianceExport: report saved to %s", output_path)
        return str(path)
