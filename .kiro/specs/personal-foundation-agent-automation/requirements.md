# Requirements Document

## Introduction

Bob Rapp and Ken Johnston, co-founders of the AIGovOps Foundation (aigovops.community), need an
automation system that lets two people run a nonprofit foundation and their personal professional
work at the scale of a full team — without hiring. This is an **internal** system for Bob and Ken
themselves, not a product sold to customers (that is the separate ai-bob-setup-agent project).

The system automates the administrative, content, community, and research work that a smart
executive assistant or small ops team would otherwise handle. It covers two domains:

1. **Personal work automation** — Bob's day-to-day: email triage, calendar management, research,
   writing, and task tracking.
2. **Foundation work automation** — AIGovOps Foundation operations: Circle.so community
   management, content creation, outreach, governance reporting, and event coordination.

Every meaningful action the system takes must be logged per the AIGovOps provenance rule:
operator, timestamp, model, prompt summary, result summary, and git SHA — append-only to
`logs/audit.jsonl` and `docs/build-log.md`.

The system is distinct from the customer-facing ai-bob-setup-agent in that it serves Bob and Ken
directly, uses their personal tool stack (Superhuman, Granola, Trello, Asana, Telegram, Loom),
and is never resold or white-labeled.

---

## Glossary

- **Automation_System**: The personal + foundation agent automation system described in this document.
- **Bob**: Bob Rapp, co-founder of the AIGovOps Foundation, primary operator of this system.
- **Ken**: Ken Johnston, co-founder of the AIGovOps Foundation, secondary operator.
- **Foundation**: The AIGovOps Foundation (aigovops.community).
- **Community**: The AIGovOps Foundation Circle.so community at aigovops.community.
- **Audit_Logger**: The append-only logging subsystem that records every agent action per the AIGovOps provenance rule, implemented on the pattern of `src/audit_log.py`.
- **Email_Agent**: The agent responsible for triaging, drafting, and routing email in Superhuman.
- **Calendar_Agent**: The agent responsible for scheduling, meeting prep, and follow-up.
- **Research_Agent**: The agent responsible for gathering, summarizing, and filing research.
- **Writing_Agent**: The agent responsible for drafting content, posts, newsletters, and reports.
- **Task_Agent**: The agent responsible for managing tasks across Trello and Asana.
- **Community_Agent**: The agent responsible for Circle.so community management (welcome, curate, moderate).
- **Welcomer**: The Community_Agent sub-role that greets new Circle.so members.
- **Curator**: The Community_Agent sub-role that produces weekly digests and member spotlights.
- **Moderator**: The Community_Agent sub-role that classifies and flags content for human review.
- **Orchestrator**: The meta-agent that coordinates all other agents and surfaces decisions to Bob and Ken via Telegram.
- **Approval_Queue**: The Telegram channel through which Bob or Ken approve or reject agent-drafted actions before they are executed.
- **Provenance_Rule**: The AIGovOps Foundation requirement that every meaningful automated action is logged with operator, UTC timestamp, model, prompt summary, result summary, and git SHA.
- **Dry_Run_Mode**: An execution mode in which the Automation_System logs all intended actions but does not execute them against external services.
- **Platform_Stack**: The set of tools already in use — Circle.so, Make.com, Telegram, Trello, Asana, Granola, Loom, Superhuman — that the Automation_System integrates with.
- **Engagement**: The combined count of reactions and comments on a Circle.so post, used as the primary signal for curation ranking.
- **Pipeline_Stage**: One of the following outreach states: new, first-contact-sent, responded-interested, responded-not-interested, needs-more-info, partner-confirmed, archived.

---

## Requirements

### Requirement 1: Personal Email Triage and Drafting

**User Story:** As Bob, I want my email inbox triaged and draft replies prepared automatically, so that I can process email in minutes rather than hours each day.

#### Acceptance Criteria

1. WHEN a new email arrives in Superhuman, THE Email_Agent SHALL classify it into one of the following categories: action-required, FYI-only, newsletter, spam, or foundation-business, within 5 minutes of arrival.
2. WHEN an email is classified as action-required, THE Email_Agent SHALL draft a reply containing a subject line and reply body, and place it in the Approval_Queue for Bob to review before sending.
3. WHEN an email is classified as FYI-only, THE Email_Agent SHALL archive it and add a one-sentence summary to the daily digest.
4. WHEN an email is classified as newsletter, THE Email_Agent SHALL archive it and extract any items that match at least one of the following keywords or topics — AI governance, responsible AI, AI regulation, AIGovOps Foundation — into the Research_Agent's input queue.
5. IF an email cannot be classified with confidence above 70%, THEN THE Email_Agent SHALL flag it for Bob's manual review without drafting a reply.
6. IF an email is classified with confidence above 70% but does not match any of the five defined categories, THEN THE Email_Agent SHALL flag it for Bob's manual review.
7. WHEN an action-required email is placed in the Approval_Queue without a draft reply, THE Email_Agent SHALL include a note indicating that no draft was generated, so Bob can write a reply from scratch.
8. WHEN THE Email_Agent classifies an email or generates a draft, THE Email_Agent SHALL log the event to the Audit_Logger with the model used, the classification result, and the draft subject line (or a null subject line marker if no draft was generated).
9. THE Email_Agent SHALL process no more than 50 emails per hour to avoid triggering Superhuman rate limits.
10. IF THE Email_Agent fails to generate a draft for an action-required email, THEN THE Email_Agent SHALL place the email in the Approval_Queue with a note indicating the draft generation failure, so Bob can write a reply from scratch.

---

### Requirement 2: Calendar Management and Meeting Preparation

**User Story:** As Bob, I want meeting scheduling and preparation handled automatically, so that I arrive at every meeting briefed and my calendar stays clean without manual effort.

#### Acceptance Criteria

1. WHEN a meeting request arrives for a slot that is unavailable, THE Calendar_Agent SHALL propose three alternative times within the next 5 business days between 09:00 and 18:00 in Bob's local timezone, and place the scheduling decision in the Approval_Queue.
2. WHEN a meeting request arrives for a slot that is available, THE Calendar_Agent SHALL place the scheduling confirmation in the Approval_Queue without proposing alternatives.
3. WHEN a meeting is confirmed and is within 24 hours, THE Calendar_Agent SHALL generate a briefing document containing: attendee backgrounds (sourced from prior Granola notes or public profiles), the 5 most recent Granola meeting notes that include at least one of the same attendees, and a suggested agenda.
4. WHEN a meeting ends, THE Calendar_Agent SHALL retrieve the Granola meeting notes and extract action items, assigning each to the named person in Asana within 30 minutes of meeting end; IF an action item names a person who cannot be resolved to an Asana user, THE Calendar_Agent SHALL assign the task to Bob with a note indicating the unresolved assignee.
5. WHEN a recurring meeting session ends, THE Calendar_Agent SHALL append the session's decisions and action items to the running context document for that series.
6. IF a meeting is cancelled within 2 hours of its start time, THEN THE Calendar_Agent SHALL release the time block and suggest one of the following alternative uses: focused work, admin catch-up, or rest; THE Calendar_Agent SHALL also attempt to notify Bob via Telegram, and if the notification fails, THE Calendar_Agent SHALL log the failure without blocking the time block release.
7. THE Calendar_Agent SHALL log every scheduling action and briefing generation to the Audit_Logger.

---

### Requirement 3: Research Gathering and Summarization

**User Story:** As Bob, I want relevant AI governance research gathered and summarized automatically, so that I stay current without spending hours reading.

#### Acceptance Criteria

1. WHEN the Research_Agent runs its daily scan, THE Research_Agent SHALL search for items published within the prior 24 hours on AI governance, responsible AI, and AI regulation using Perplexity MCP.
2. WHEN a research item is found, THE Research_Agent SHALL score its relevance to the Foundation's four pillars (Governance as Code, AI Technical Debt, Operational Compliance, Community-Driven Standards) on a scale of 1–5, where 5 means the item directly addresses a pillar and 1 means it is tangentially related.
3. WHEN a research item scores 4 or higher, THE Research_Agent SHALL draft a summary of no more than 150 words and add it to the weekly Foundation newsletter draft.
4. WHEN a research item scores 3 or lower, THE Research_Agent SHALL file it in the research archive without surfacing it to Bob.
5. WHEN the daily scan produces at least one item scored 4 or higher, THE Research_Agent SHALL deliver a digest of those items to Bob via Telegram by 08:00 Pacific time on the next weekday.
6. IF the daily scan produces no items scored 4 or higher, THE Research_Agent SHALL send Bob a brief Telegram message stating that no high-relevance items were found that day.
7. IF the Perplexity MCP scan fails, THE Research_Agent SHALL log the failure to the Audit_Logger and notify Bob via Telegram; THE Research_Agent SHALL NOT deliver a digest for that day.
8. IF the Telegram delivery of the digest fails, THE Research_Agent SHALL log the failure to the Audit_Logger and retry once after 15 minutes; if the retry also fails, THE Research_Agent SHALL log the second failure without further retries.
9. WHEN THE Research_Agent completes a scan, scoring run, or digest delivery, THE Research_Agent SHALL log the event to the Audit_Logger with the model used and the number of items processed.
10. FOR ALL research items processed in a single scan session, THE Research_Agent SHALL produce a structured JSON output such that re-parsing that output yields records with identical pillar scores and summary text (deterministic round-trip property).

---

### Requirement 4: Content Creation and Writing Assistance

**User Story:** As Bob and Ken, we want first drafts of Foundation content produced automatically, so that we spend our time editing and approving rather than writing from scratch.

#### Acceptance Criteria

1. WHEN Bob or Ken requests a content draft via Telegram, THE Writing_Agent SHALL produce a first draft within 10 minutes, written in the AIGovOps Foundation voice, defined as: practitioner-first framing (lead with operational insight, not theory), no marketing superlatives (no "revolutionary", "game-changing", or similar), and no calls-to-action directing readers to purchase or sign up.
2. WHEN a weekly newsletter is due (every Monday), THE Writing_Agent SHALL assemble a draft from the Research_Agent's weekly digest, the Community Curator's digest, and any flagged items, and place it in the Approval_Queue by Sunday 6:00 PM Pacific.
3. WHEN a LinkedIn post is requested, THE Writing_Agent SHALL produce three variant drafts: short (50–100 words), medium (150–250 words), and long-form (400–600 words), for Bob or Ken to choose from.
4. WHEN a draft is placed in the Approval_Queue, THE Writing_Agent SHALL include a one-line rationale for each of the following editorial choices where they occur: source selection or omission, topic scope change from the request, and format restructure.
5. IF a draft is rejected by Bob or Ken with feedback that does not require new sourcing or a format type change, THEN THE Writing_Agent SHALL revise the draft incorporating the feedback and resubmit to the Approval_Queue within 10 minutes.
6. IF a draft is rejected by Bob or Ken with feedback that requires new sourcing or a format type change, THEN THE Writing_Agent SHALL notify Bob or Ken of the estimated revision time (not to exceed 60 minutes) before proceeding, then revise and resubmit to the Approval_Queue.
7. THE Writing_Agent SHALL never publish content directly; all content SHALL pass through the Approval_Queue before any external publication.
8. THE Writing_Agent SHALL log every draft creation, revision, and approval event to the Audit_Logger.

---

### Requirement 5: Task and Project Tracking

**User Story:** As Bob and Ken, we want our tasks and project state kept current automatically, so that Trello and Asana reflect reality without manual updates.

#### Acceptance Criteria

1. WHEN an action item is extracted from a Granola meeting note, THE Task_Agent SHALL create a corresponding task in Asana with the assignee, due date (defaulting to 5 business days if not specified), and source meeting reference; IF no assignee is named in the meeting note, THE Task_Agent SHALL assign the task to Bob with a note indicating the assignee was not specified.
2. WHEN a task in Asana has been open for more than 7 days without a status change, comment, due-date change, or assignee change, THE Task_Agent SHALL send a reminder to the assignee via Telegram.
3. WHEN a task is marked complete in Asana, THE Task_Agent SHALL update the corresponding Trello card to reflect the completion; IF no corresponding Trello card exists, THE Task_Agent SHALL log the missing card to the Audit_Logger and take no further action.
4. WHEN a Foundation project milestone is 3 or fewer days away, THE Task_Agent SHALL send a status summary to Bob and Ken via Telegram at 08:00 Pacific each morning until the milestone passes, including the milestone name, due date, and count of open blocking tasks.
5. WHEN Friday 5:00 PM Pacific arrives, THE Task_Agent SHALL produce a weekly project status report covering all active Foundation projects and place it in the Approval_Queue for Bob's review before distribution.
6. THE Task_Agent SHALL log every task creation, reminder, and status update to the Audit_Logger.

---

### Requirement 6: Circle.so Community — Member Welcome

**User Story:** As Bob and Ken, we want every new AIGovOps Foundation community member welcomed personally and promptly, so that new members feel seen and engaged from day one.

#### Acceptance Criteria

1. WHEN a new member joins the Circle.so community, THE Welcomer SHALL send a personalized welcome DM to the new member within 5 minutes, referencing at least one specific detail from the member's introduction or profile (such as their stated role, organization, or AI governance interest).
2. WHEN a new member joins, THE Welcomer SHALL post a welcome message in the community's welcome thread within 5 minutes, tagging the new member and highlighting one relevant community resource matched to the member's stated interests.
3. WHEN a new member's introduction or profile mentions a specific AI governance topic that maps to a defined Circle.so interest tag, THE Welcomer SHALL apply that interest tag to the member's profile.
4. IF the Circle.so API is unavailable when a welcome action is triggered, THEN THE Welcomer SHALL queue the action and retry using exponential backoff starting at 30 seconds, doubling each attempt, with a maximum total retry window of 30 minutes; IF the action is not completed within 30 minutes, THE Welcomer SHALL log the failure to the Audit_Logger and notify Bob via Telegram.
5. THE Welcomer SHALL never send more than one DM per new member per join event; before sending, THE Welcomer SHALL check the Audit_Logger for a prior DM record for that member ID and join event.
6. THE Welcomer SHALL log every welcome DM and welcome post to the Audit_Logger with the member ID (not name or email), the model used, and the personalization element selected.

---

### Requirement 7: Circle.so Community — Content Curation

**User Story:** As Bob and Ken, we want the best community conversations surfaced and amplified weekly, so that members see the value of the community without us manually curating.

#### Acceptance Criteria

1. WHEN the weekly curation cycle runs (every Sunday at noon Pacific), THE Curator SHALL identify the top 3–5 community posts from the prior 7 days, ranked by Engagement (combined reactions + comments) among posts tagged with an AI governance category.
2. WHEN the Curator identifies at least one qualifying post, THE Curator SHALL draft a weekly digest post summarizing the top posts and a member spotlight for the highest-Engagement contributor (including their name, post title, and a one-sentence description of their contribution), and place both in the Approval_Queue.
3. WHEN the weekly curation cycle runs and no posts meet the qualifying criteria, THE Curator SHALL notify Bob via Telegram that no qualifying posts were found and skip the digest for that week.
4. WHEN Bob or Ken approves the digest, THE Curator SHALL publish it to the Circle.so community within 5 minutes of approval; IF the Circle.so API does not return a success response within 5 minutes, THEN THE Curator SHALL mark the publication as failed, log the failure to the Audit_Logger, and require re-approval before retrying.
5. WHEN a community thread has been inactive for more than 14 days and has an Engagement score of 5 or higher, THE Curator SHALL draft a bump comment and place it in the Approval_Queue.
6. THE Curator SHALL never publish any content to the community without explicit approval from Bob or Ken via the Approval_Queue.
7. THE Curator SHALL log every curation run, draft, approval event, and publication to the Audit_Logger.

---

### Requirement 8: Circle.so Community — Content Moderation

**User Story:** As Bob and Ken, we want community content monitored for spam, toxicity, and policy violations, so that the community remains safe and on-topic without us reading every post.

#### Acceptance Criteria

1. WHEN a new post or comment is published in the Circle.so community, THE Moderator SHALL classify it for spam, toxicity, PII exposure, scam links, and off-topic content within 5 minutes.
2. WHEN a post is classified as spam or containing a scam link with confidence above 90%, THE Moderator SHALL flag it in the human review queue and notify Bob or Ken via Telegram within 60 seconds of classification.
3. WHEN a post is classified as toxic or containing PII with confidence above 80%, THE Moderator SHALL flag it in the human review queue and notify Bob or Ken via Telegram within 5 minutes of classification.
4. IF the Telegram notification in criteria 2 or 3 fails, THEN THE Moderator SHALL log the notification failure to the Audit_Logger and retry once after 60 seconds; if the retry also fails, THE Moderator SHALL log the second failure without further retries.
5. WHEN a post is classified as off-topic with confidence above 85%, THE Moderator SHALL draft a redirect comment of no more than 280 characters and place it in the Approval_Queue for Bob or Ken to review before posting.
6. IF a post classification confidence is below the applicable threshold in criteria 2, 3, or 5, THEN THE Moderator SHALL log the classification result to the Audit_Logger without taking any further action.
7. THE Moderator SHALL never auto-remove or auto-hide content; all removal actions SHALL require explicit approval from Bob or Ken.
8. THE Moderator SHALL log every classification event to the Audit_Logger with the post ID (not content), the model used, the classification result, and the confidence score.

---

### Requirement 9: Outreach and Partnership Coordination

**User Story:** As Bob and Ken, we want outreach to potential Foundation partners, speakers, and community members managed systematically, so that no relationship falls through the cracks.

#### Acceptance Criteria

1. WHEN Bob or Ken adds a contact to the outreach pipeline via Telegram, THE Task_Agent SHALL create an outreach task in Asana with the contact's name and Pipeline_Stage set to "new", and place a suggested first-contact message draft in the Approval_Queue.
2. WHEN an outreach contact has not received a follow-up within 7 days of the most recent sent or received message, THE Task_Agent SHALL draft a follow-up message and place it in the Approval_Queue; IF the draft generation fails, THE Task_Agent SHALL retry up to 3 times at 60-second intervals; if all retries fail, THE Task_Agent SHALL log the failure to the Audit_Logger and notify Bob via Telegram.
3. WHEN a contact responds to an outreach message and the response is classified as interested, THE Email_Agent SHALL update the contact's Pipeline_Stage to "responded-interested" and create a follow-up task in Asana.
4. WHEN a contact responds and the response is classified as not-interested, THE Email_Agent SHALL update the contact's Pipeline_Stage to "responded-not-interested" and archive the outreach task.
5. WHEN a contact responds and the response is classified as needs-more-info, THE Email_Agent SHALL draft an informational reply and place it in the Approval_Queue.
6. WHEN Friday 5:00 PM Pacific arrives, THE Task_Agent SHALL produce an outreach status report showing each active contact's name, Pipeline_Stage, and last-contact date, and deliver it to Bob via Telegram.
7. THE Task_Agent SHALL log every outreach task creation, follow-up draft, Pipeline_Stage change, and status update to the Audit_Logger.

---

### Requirement 10: Governance Reporting and Observability

**User Story:** As Bob and Ken, we want automated reports on Foundation activity and system health, so that we have evidence of impact and can catch problems before they compound.

#### Acceptance Criteria

1. WHEN an agent action occurs, THE Audit_Logger SHALL record the event with: operator identity, UTC timestamp, agent name, action type, model used, prompt summary (not verbatim prompt, max 200 characters), result summary (max 200 characters), status (success / failure / partial), and git SHA of the running code.
2. THE Audit_Logger SHALL write records in append-only JSONL format to `logs/audit.jsonl`, with no record ever modified or deleted after writing.
3. WHEN an agent action fails, THE Audit_Logger SHALL record the failure with the error class and a non-sensitive error summary (excluding credentials, tokens, and PII, max 500 characters) before the Automation_System attempts any retry.
4. WHEN Friday 5:00 PM Pacific arrives, THE Automation_System SHALL produce a weekly governance report summarizing: total actions taken, actions by agent, approval queue throughput, failure rate, and any anomalies (defined as any agent with a failure rate above 10% or more than 5 consecutive failures in the reporting period).
5. WHEN the failure rate for any single agent exceeds 10% in a 24-hour window, THE Orchestrator SHALL notify Bob via Telegram within 60 seconds and suspend that agent's autonomous actions until Bob sends an explicit acknowledgement via Telegram.
6. THE Orchestrator SHALL support manual suspension of any agent via a Telegram command from Bob or Ken, independent of the failure rate threshold.
7. THE Automation_System SHALL expose a read-only audit log viewer accessible to Bob and Ken that displays the last 100 entries with filtering by agent, date, and status.
8. FOR ALL audit log entries written during a single process run, THE Audit_Logger SHALL produce JSONL output such that re-parsing each line yields a record with field values identical to those originally written (deterministic round-trip property).
9. IF the weekly governance report delivery fails, THE Automation_System SHALL log the failure to the Audit_Logger and retry once after 15 minutes; if the retry also fails, THE Automation_System SHALL log the second failure without further retries.

---

### Requirement 11: Agent Platform and Integration Architecture

**User Story:** As Bob, I want the automation system built on a platform that integrates with my existing tools, supports the AIGovOps provenance rule, and can be extended without rewriting everything, so that I'm not locked into a single vendor.

#### Acceptance Criteria

1. THE Automation_System SHALL integrate with Circle.so via the Circle Admin API for community management actions (member lookup, DM delivery via Headless Auth JWT, post creation, content flagging).
2. WHEN a Make.com scenario completes (whether success or failure), THE Automation_System SHALL invoke the Audit_Logger shim, recording at minimum the scenario name, completion status, and UTC timestamp.
3. IF a workflow requires only in-platform Circle.so data and actions (onboarding flows, keyword tagging, or profanity filtering), THEN THE Automation_System SHALL execute that workflow using Circle.so native AI Workflows without routing through Make.com.
4. WHERE Sintra or Marblism is considered for a sub-task, THE Automation_System SHALL only adopt that platform if it exposes a customer-accessible per-action audit log with timestamps and model inputs/outputs; platforms that do not meet this requirement SHALL be excluded.
5. THE Automation_System SHALL integrate with Telegram as the primary human-in-the-loop channel for the Approval_Queue and all agent notifications to Bob and Ken.
6. THE Automation_System SHALL integrate with Asana and Trello via Composio for task and project management actions.
7. WHEN meeting notes are requested, THE Automation_System SHALL retrieve the corresponding Granola record via its export API or webhook, including at minimum the meeting title, date, and summary or transcript.
8. WHEN Dry_Run_Mode is active, THE Automation_System SHALL record each intended action as an audit log entry with the `dry_run` flag set to `true` and SHALL NOT execute any external API calls.
9. THE Automation_System SHALL be deployable from this repository using `make install` on a machine with bash, Python 3.11 or later, make, and git available, with the command exiting zero and leaving the system ready to run `make onboard`.

---

### Requirement 12: Human-in-the-Loop and Approval Governance

**User Story:** As Bob and Ken, we want every consequential agent action to require our explicit approval before execution, so that the system amplifies our judgment rather than replacing it.

#### Acceptance Criteria

1. WHEN an agent places an action in the Approval_Queue, THE Approval_Queue SHALL present it to Bob or Ken via Telegram with: a plain-language description of the action, the draft content or decision, the agent that generated it, and inline approve / reject / edit buttons.
2. WHEN Bob or Ken taps the edit button on a queued action, THE Orchestrator SHALL accept the edited content, replace the original draft in the queue, and re-present the updated action for final approve / reject.
3. WHEN Bob or Ken approves an action, THE Orchestrator SHALL log the approval event to the Audit_Logger first, then execute the action within 2 minutes; IF the Audit_Logger is unavailable at approval time, THE Orchestrator SHALL proceed with execution and log the approval as soon as the logger recovers.
4. WHEN Bob or Ken rejects an action, THE Orchestrator SHALL log the rejection (including the reason if provided) to the Audit_Logger, notify the originating agent to revise or discard, and if the agent revises, re-enter the revised action into the Approval_Queue.
5. WHEN an action in the Approval_Queue has not been reviewed within 24 hours, THE Orchestrator SHALL send a reminder to both Bob and Ken via Telegram.
6. IF the Approval_Queue contains more than 10 pending items, THEN THE Orchestrator SHALL send a summary digest to Bob listing the count and types of pending actions, rather than individual notifications, to avoid notification fatigue.
7. THE Automation_System SHALL maintain a complete record of every approval and rejection in the Audit_Logger, including: reviewer identity, UTC timestamp, action type, agent name, and reason for rejection where provided.
8. THE Automation_System SHALL never take an action that sends external communications (email, community posts, social media) without a logged approval from Bob or Ken.

---

### Requirement 13: Differentiation from the Customer-Facing ai-bob-setup-agent

**User Story:** As Bob, I want this internal system clearly separated from the customer-facing ai-bob-setup-agent product, so that there is no confusion between what I use for myself and what I sell to customers.

#### Acceptance Criteria

1. THE Automation_System SHALL be implemented in `src/personal_foundation/` with no cross-imports between that package and `src/setup_agent.py` or any other module in the customer-provisioning path.
2. WHEN THE Automation_System logs an action to the Audit_Logger, the `agent` field SHALL be prefixed with `personal/` (for Bob's personal automation agents) or `foundation/` (for Foundation-facing agents) to distinguish internal actions from customer-provisioning actions in the log.
3. IF Hermes or OpenClaw is used for a sub-component of the Automation_System, THEN that sub-component SHALL reside in `src/personal_foundation/`, SHALL NOT share runtime code with `src/setup_agent.py`, SHALL be documented in `docs/personal-foundation-runbook.md`, and its configuration SHALL be stored in `config/personal-foundation/` and gitignored.
4. THE Automation_System SHALL be documented in `docs/personal-foundation-runbook.md`, which SHALL include the header "INTERNAL USE ONLY — not part of the ai-bob-setup-agent customer product" on the first line.
5. THE Automation_System's configuration SHALL be stored in `config/personal-foundation/` and SHALL be covered by a `config/personal-foundation/` entry in `.gitignore`, consistent with the existing pattern for customer configs.
