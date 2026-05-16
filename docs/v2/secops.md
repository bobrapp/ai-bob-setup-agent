# Security Operations (SecOps)

## Threat Model

| Threat | Likelihood | Impact | Mitigation |
|--------|-----------|--------|------------|
| API key leaked in logs | Medium | High | Policy engine blocks logging of secrets; audit shim truncates |
| Agent sends unauthorized email | Low | High | Cedar policy: all external comms require approval |
| Malicious community post triggers harmful agent action | Medium | Medium | Moderator never auto-removes; all actions require approval |
| SQLite database stolen | Low | High | SQLCipher encryption at rest |
| Telegram bot token compromised | Low | High | Token in keychain, not files; bot restricted to known chat IDs |
| LLM prompt injection via email | Medium | Medium | Agent outputs are structured (Pydantic); actions are policy-gated |
| Denial of service (flood of events) | Low | Low | Rate limiting on API gateway; agent concurrency semaphore |

---

## Security Principles

1. **Least privilege:** Each agent can only do what its Cedar policy permits
2. **Defense in depth:** Policy + approval queue + audit log = three independent barriers
3. **Fail closed:** If policy evaluation fails, action is denied (not permitted)
4. **No secrets in motion:** API keys read once at startup, never passed between components
5. **Immutable audit:** Append-only log; no UPDATE or DELETE on audit_log table
6. **Metadata only:** Logs contain IDs and summaries, never full content

---

## Cedar Policy Examples

### Agent permissions
```cedar
// Moderator can flag but never delete
permit(
  principal == Agent::"foundation/moderator",
  action == Action::"flag_post",
  resource in ResourceType::"circle_post"
);
forbid(
  principal == Agent::"foundation/moderator",
  action in [Action::"delete_post", Action::"hide_post"],
  resource
);

// Welcomer can send DMs without approval (pre-approved by policy)
permit(
  principal == Agent::"foundation/welcomer",
  action == Action::"send_dm",
  resource in ResourceType::"circle_member"
) when { resource.is_new_member == true };

// All agents can log to audit (always permitted)
permit(
  principal in AgentGroup::"all_agents",
  action == Action::"log_audit",
  resource in ResourceType::"audit_log"
);
```

### Approval permissions
```cedar
// Only Bob and Ken can approve
permit(
  principal in Group::"operators",
  action in [Action::"approve", Action::"reject", Action::"edit"],
  resource in ResourceType::"approval_item"
);

// No one else can approve
forbid(
  principal,
  action in [Action::"approve", Action::"reject", Action::"edit"],
  resource in ResourceType::"approval_item"
) unless { principal in Group::"operators" };
```

### Data protection
```cedar
// Never log PII
forbid(
  principal,
  action == Action::"log_audit",
  resource
) when { resource.contains_pii == true };

// Never log email bodies
forbid(
  principal,
  action == Action::"log_audit",
  resource in ResourceType::"email"
) when { resource.field == "body" };

// Never log API keys
forbid(
  principal,
  action == Action::"log_audit",
  resource
) when { resource.contains_secret == true };
```

---

## Authentication & Authorization

| Component | Auth method | Scope |
|-----------|------------|-------|
| Web UI | JWT (HS256, 24h expiry) | Bob + Ken only |
| Telegram | Chat ID whitelist | Bob + Ken chat IDs only |
| Voice (Siri) | JWT embedded in Shortcut | Bob only |
| API | JWT Bearer token | Bob + Ken |
| Agent-to-API | Internal (no auth, same process) | All agents |

### JWT Claims
```json
{
  "sub": "bob",
  "name": "Bob Rapp",
  "role": "operator",
  "iat": 1716854400,
  "exp": 1716940800
}
```

---

## Incident Response

### Agent misbehavior
1. Auto-detected: failure rate >10% → auto-suspend → Telegram alert
2. Manual: `/suspend <agent>` via Telegram or web UI
3. Investigate: `python scripts/audit_viewer.py --agent <name> --status failure --limit 20`
4. Fix: Update agent YAML or policy → hot-reload (no restart)
5. Resume: `/resume <agent>`
6. Log: Incident recorded in audit log with resolution

### API key compromise
1. Revoke key at provider (OpenAI/Groq/Circle/etc.)
2. Generate new key
3. Update keychain: `security add-generic-password -a aigovops -s OPENAI_API_KEY -w NEW_KEY`
4. Restart process: `systemctl restart aigovops-automation`
5. Verify: `make doctor-foundation`

### Data breach (SQLite stolen)
1. SQLCipher encryption means data is unreadable without passphrase
2. Rotate all API keys (they're in the DB config table)
3. Revoke JWT signing key (invalidates all sessions)
4. Notify: Ken via Telegram
5. Audit: Check audit log for unauthorized access patterns

---

## Compliance Checklist

| Requirement | Implementation | Verified by |
|-------------|---------------|-------------|
| Every action logged | Audit shim enforces logging before execution | PBT Property 1 |
| No PII in logs | Cedar policy + audit shim truncation | PBT Property 7 |
| Approval before external comms | Cedar policy + queue enforcement | PBT Property 10 |
| Immutable audit trail | SQLite append-only (no UPDATE/DELETE) | E2E test |
| Secrets not in git | .gitignore + keychain storage | CI check |
| Encryption at rest | SQLCipher on foundation.db | Deployment script |
| Agent isolation | No cross-imports, prefixed actions | E2E test |
| Operator identity on every action | JWT claims propagated to audit entries | Unit test |
