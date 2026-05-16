"""AIGovOps Agent Framework — policy-gated, event-driven AI agent runtime.

Install: pip install aigovops-agent-framework
Docs: https://bobrapp.github.io/ai-bob-setup-agent/

Quick start:
    from aigovops_framework import Framework

    fw = Framework()
    fw.load_agents("agents/")
    fw.load_policies("policies/")
    fw.start()

Features:
- YAML-defined agents (no Python per agent)
- Cedar-style policy-as-code
- Event-driven architecture (SQLite-backed)
- Multi-channel notifications (Telegram, WhatsApp, SMS, Web, Voice)
- LLM response caching + cost tracking
- Feedback loops (learns from operator edits)
- Human-in-the-loop approval queue
- Immutable audit log
"""

__version__ = "0.1.0"

from aigovops_framework.core import Framework
from aigovops_framework.state import StateStore
from aigovops_framework.events import EventBus
from aigovops_framework.policy import PolicyEngine, PolicyContext, PolicyDecision
from aigovops_framework.engine import AgentEngine
from aigovops_framework.cache import LLMCache
from aigovops_framework.costs import CostTracker
from aigovops_framework.feedback import FeedbackStore

__all__ = [
    "Framework",
    "StateStore",
    "EventBus",
    "PolicyEngine",
    "PolicyContext",
    "PolicyDecision",
    "AgentEngine",
    "LLMCache",
    "CostTracker",
    "FeedbackStore",
]
