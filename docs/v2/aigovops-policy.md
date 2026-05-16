# AIGovOps Foundation — Policy as Code

## Overview

The AIGovOps Foundation practices what it preaches: AI governance implemented as executable, testable, version-controlled policy. This document defines the governance framework that the automation system enforces.

---

## The Three Pillars of AIGovOps Policy

### 1. Ship AI (Enable)
Policies that enable agents to act autonomously where safe:
- Welcomer can send DMs to new members without approval
- Research Agent can scan and score without approval
- Task Agent can send reminders without approval
- Agents can log to audit without approval

### 2. Steady AI (Govern)
Policies that require human oversight for consequential actions:
- All external communications require approval
- Content publication requires approval
- Outreach messages require approval
- Agent suspension/resumption requires operator action

### 3. Recover AI (Protect)
Policies that protect against failure and misuse:
- Auto-suspension on high failure rates
- No agent can delete or hide community content
- No PII in audit logs
- Encrypted state at rest
- Immutable audit trail

---

## Policy File Structure

```
policies/
├── approval.cedar          # Who can approve what
├── agents/
│   ├── email.cedar         # Email agent permissions
│   ├── welcomer.cedar      # Welcomer permissions
│   ├── moderator.cedar     # Moderator restrictions
│   ├── curator.cedar       # Curator permissions
│   ├── writer.cedar        # Writing agent permissions
│   ├── researcher.cedar    # Research agent permissions
│   ├── task.cedar          # Task agent permissions
│   └── calendar.cedar      # Calendar agent permissions
├── data.cedar              # Data protection rules
├── security.cedar          # Authentication and access control
└── operational.cedar       # Rate limits, timeouts, failure handling
```

---

## Governance Rules (Executable)

### Rule 1: Provenance
Every meaningful action MUST be logged with:
- Operator identity (who triggered or approved)
- UTC timestamp
- Agent name (prefixed personal/ or foundation/)
- Action type
- Model used
- Prompt summary (max 200 chars, no secrets)
- Result summary (max 200 chars)
- Status (success/failure/partial)
- Git SHA of running code

**Enforcement:** `audit_shim.py` raises ValueError if any required field is missing.

### Rule 2: Human-in-the-Loop
No agent SHALL send external communications without a logged approval from an operator.

**Enforcement:** Cedar policy `forbid` on all `send_*` actions unless `approval.exists == true`.

### Rule 3: No Auto-Removal
No agent SHALL delete, hide, or remove community content without explicit operator approval.

**Enforcement:** Cedar policy `forbid` on `delete_post` and `hide_post` for all agents.

### Rule 4: Data Minimization
Audit logs SHALL contain only metadata. Never:
- Email bodies
- Post content
- Member names (use IDs)
- API keys or tokens
- Passwords

**Enforcement:** Cedar policy `forbid` on logging when `resource.contains_pii == true`.

### Rule 5: Fail Safe
If an agent's failure rate exceeds 10% in a 24-hour window, it SHALL be automatically suspended until an operator acknowledges.

**Enforcement:** Orchestrator monitors audit log; suspends agent; requires `/resume` command.

### Rule 6: Least Privilege
Each agent SHALL have only the permissions it needs. No agent has blanket access to all integrations.

**Enforcement:** Per-agent Cedar policy files define exactly what each agent can do.

### Rule 7: Transparency
Every policy evaluation (permit or deny) SHALL be logged. Operators can see why an action was allowed or blocked.

**Enforcement:** Policy engine logs every evaluation to audit with the policy file and rule that matched.

---

## Policy Testing

Policies are tested like code:

```bash
# Validate policy syntax
cedar validate policies/

# Run policy test suite
cedar test policies/ --test-suite tests/policy_tests/

# Example test
# tests/policy_tests/moderator_cannot_delete.cedar_test
test "moderator cannot delete posts" {
  expect deny(
    principal: Agent::"foundation/moderator",
    action: Action::"delete_post",
    resource: Post { id: "p123" }
  )
}
```

---

## Governance Reporting

Weekly governance report (auto-generated Friday 5 PM) includes:
- Total actions taken by all agents
- Actions by agent (breakdown)
- Approval queue throughput (approved + rejected)
- Failure rate per agent
- Policy denials (actions that were blocked)
- Anomalies (agents above thresholds)

This report is itself an approval queue item — Bob reviews before it's filed.

---

## Version Control

All policies are:
- Stored in git (`policies/` directory)
- Reviewed via PR before merge
- Logged in `docs/build-log.md` when changed
- Hot-reloaded on file change (no restart needed)
- Tested in CI before deployment

---

## Audit Trail Format

```json
{
  "seq": 1042,
  "timestamp": "2026-05-15T22:30:00Z",
  "operator": "bob",
  "agent": "foundation/moderator",
  "action": "classify_post",
  "model": "groq/llama-3.1-70b-versatile",
  "prompt_summary": "Classify post p789 for moderation",
  "result_summary": "spam=0.12 toxic=0.03 off_topic=0.85",
  "status": "success",
  "policy_evaluation": "permit (agents/moderator.cedar:line 3)",
  "dry_run": false,
  "git_sha": "1523a42"
}
```
