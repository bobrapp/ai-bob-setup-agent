"""Alexa Skill Lambda handler for AIGovOps Agent Framework.

Deploy this as an AWS Lambda function connected to your Alexa Skill.
Set environment variables: API_URL, API_TOKEN
"""

from __future__ import annotations

import json
import os
import urllib.request

API_URL = os.environ.get("API_URL", "https://your-server.com")
API_TOKEN = os.environ.get("API_TOKEN", "")


def lambda_handler(event, context):
    """Main Alexa handler."""
    request_type = event.get("request", {}).get("type", "")

    if request_type == "LaunchRequest":
        return build_response("Welcome to AI Gov Ops. You can ask what's pending, get a daily summary, or draft content.")

    if request_type == "IntentRequest":
        intent = event["request"]["intent"]["name"]
        slots = event["request"]["intent"].get("slots", {})
        return handle_intent(intent, slots)

    return build_response("Goodbye!")


def handle_intent(intent: str, slots: dict) -> dict:
    """Route intents to API calls."""
    if intent == "WhatssPendingIntent":
        return call_voice_api("whats_pending", {})

    elif intent == "ApproveLowRiskIntent":
        return call_voice_api("approve_all_low_risk", {})

    elif intent == "SuspendAgentIntent":
        agent = slots.get("agentName", {}).get("value", "")
        if not agent:
            return build_response("Which agent should I suspend?", should_end=False)
        return call_voice_api("suspend", {"agent": agent})

    elif intent == "DailySummaryIntent":
        return call_voice_api("daily_summary", {})

    elif intent == "DraftContentIntent":
        topic = slots.get("topic", {}).get("value", "")
        if not topic:
            return build_response("What should I draft about?", should_end=False)
        return call_voice_api("draft", {"topic": topic})

    elif intent in ("AMAZON.HelpIntent",):
        return build_response(
            "You can say: what's pending, approve low risk, daily summary, "
            "suspend an agent, or draft about a topic."
        )

    elif intent in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
        return build_response("Goodbye!")

    return build_response("I didn't understand that. Try: what's pending?")


def call_voice_api(command: str, params: dict) -> dict:
    """Call the AIGovOps /api/voice endpoint."""
    try:
        data = json.dumps({"command": command, "params": params}).encode()
        req = urllib.request.Request(
            f"{API_URL}/api/voice",
            data=data,
            headers={
                "Authorization": f"Bearer {API_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            speech = result.get("speech", "Something went wrong.")
            return build_response(speech)
    except Exception as exc:
        return build_response(f"Sorry, I couldn't reach the server. Error: {str(exc)[:50]}")


def build_response(speech: str, should_end: bool = True) -> dict:
    """Build an Alexa response."""
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": speech,
            },
            "shouldEndSession": should_end,
        },
    }
