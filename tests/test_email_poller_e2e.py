"""End-to-end tests for the email poller and cost dashboard.

Tests the complete email polling flow without external credentials:
- Email message parsing and classification
- Seen-UID deduplication
- Cost logging and aggregation
- Cost data generation
- Telegram notification formatting
- Poll cycle stats

Run: python3 -m pytest tests/test_email_poller_e2e.py -v
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory for cost/seen files."""
    return tmp_path


@pytest.fixture
def poller_module():
    """Import the email poller module."""
    import scripts.email_poller as ep
    return ep


@pytest.fixture
def cost_gen_module():
    """Import the cost data generator module."""
    import scripts.generate_cost_data as cg
    return cg


# ---------------------------------------------------------------------------
# EmailMessage Tests
# ---------------------------------------------------------------------------

class TestEmailMessage:
    """Test EmailMessage dataclass and parsing helpers."""

    def test_email_message_creation(self, poller_module):
        msg = poller_module.EmailMessage(
            uid="123",
            from_addr="sender@example.com",
            subject="Test Subject",
            body="Hello, this is a test email body.",
            to_addr="bob@example.com",
            snippet="Hello, this is a test",
        )
        assert msg.uid == "123"
        assert msg.from_addr == "sender@example.com"
        assert msg.subject == "Test Subject"
        assert msg.body == "Hello, this is a test email body."

    def test_email_message_defaults(self, poller_module):
        msg = poller_module.EmailMessage(
            uid="456",
            from_addr="x@y.com",
            subject="Sub",
            body="Body",
        )
        assert msg.date is None
        assert msg.to_addr == ""
        assert msg.snippet == ""


# ---------------------------------------------------------------------------
# Classification Result Tests
# ---------------------------------------------------------------------------

class TestClassificationResult:
    """Test ClassificationResult dataclass."""

    def test_default_values(self, poller_module):
        result = poller_module.ClassificationResult()
        assert result.category == "unknown"
        assert result.confidence == 0.0
        assert result.draft == ""
        assert result.reasoning == ""

    def test_custom_values(self, poller_module):
        result = poller_module.ClassificationResult(
            category="action-required",
            confidence=0.95,
            draft="Hi, thanks for your email...",
            reasoning="Requests a meeting",
        )
        assert result.category == "action-required"
        assert result.confidence == 0.95


# ---------------------------------------------------------------------------
# Seen-UID Tracking Tests
# ---------------------------------------------------------------------------

class TestSeenUIDTracking:
    """Test deduplication via seen UIDs."""

    def test_load_empty(self, poller_module, tmp_data_dir):
        with patch.object(poller_module, 'SEEN_FILE', tmp_data_dir / "seen.json"):
            uids = poller_module.load_seen_uids()
            assert uids == set()

    def test_save_and_load(self, poller_module, tmp_data_dir):
        seen_file = tmp_data_dir / "seen.json"
        with patch.object(poller_module, 'SEEN_FILE', seen_file), \
             patch.object(poller_module, 'DATA_DIR', tmp_data_dir):
            uids = {"100", "200", "300"}
            poller_module.save_seen_uids(uids)

            loaded = poller_module.load_seen_uids()
            assert loaded == uids

    def test_save_caps_at_500(self, poller_module, tmp_data_dir):
        seen_file = tmp_data_dir / "seen.json"
        with patch.object(poller_module, 'SEEN_FILE', seen_file), \
             patch.object(poller_module, 'DATA_DIR', tmp_data_dir):
            uids = {str(i) for i in range(700)}
            poller_module.save_seen_uids(uids)

            data = json.loads(seen_file.read_text())
            assert len(data["uids"]) == 500

    def test_corrupted_file_returns_empty(self, poller_module, tmp_data_dir):
        seen_file = tmp_data_dir / "seen.json"
        seen_file.write_text("not valid json{{{")
        with patch.object(poller_module, 'SEEN_FILE', seen_file):
            uids = poller_module.load_seen_uids()
            assert uids == set()


# ---------------------------------------------------------------------------
# Cost Logging Tests
# ---------------------------------------------------------------------------

class TestCostLogging:
    """Test poll cost logging."""

    def test_log_poll_cost_creates_file(self, poller_module, tmp_data_dir):
        cost_file = tmp_data_dir / "email_poll_costs.json"
        with patch.object(poller_module, 'COST_LOG_FILE', cost_file), \
             patch.object(poller_module, 'DATA_DIR', tmp_data_dir):
            stats = poller_module.PollStats(
                fetched=5, classified=3, action_required=1,
                archived=2, errors=0, cost_usd=0.000123,
            )
            poller_module.log_poll_cost(stats)

            assert cost_file.exists()
            entries = json.loads(cost_file.read_text())
            assert len(entries) == 1
            assert entries[0]["classified"] == 3
            assert entries[0]["cost_usd"] == 0.000123

    def test_log_poll_cost_appends(self, poller_module, tmp_data_dir):
        cost_file = tmp_data_dir / "email_poll_costs.json"
        with patch.object(poller_module, 'COST_LOG_FILE', cost_file), \
             patch.object(poller_module, 'DATA_DIR', tmp_data_dir):
            for i in range(3):
                stats = poller_module.PollStats(
                    fetched=i, classified=i, action_required=0,
                    archived=i, errors=0, cost_usd=0.0001 * i,
                )
                poller_module.log_poll_cost(stats)

            entries = json.loads(cost_file.read_text())
            assert len(entries) == 3

    def test_log_poll_cost_caps_at_1000(self, poller_module, tmp_data_dir):
        cost_file = tmp_data_dir / "email_poll_costs.json"
        # Pre-populate with 999 entries
        existing = [{"timestamp": "2026-01-01", "classified": 1, "cost_usd": 0.0001}] * 999
        cost_file.write_text(json.dumps(existing))

        with patch.object(poller_module, 'COST_LOG_FILE', cost_file), \
             patch.object(poller_module, 'DATA_DIR', tmp_data_dir):
            stats = poller_module.PollStats(fetched=1, classified=1)
            poller_module.log_poll_cost(stats)
            poller_module.log_poll_cost(stats)

            entries = json.loads(cost_file.read_text())
            assert len(entries) == 1000  # Capped


# ---------------------------------------------------------------------------
# Classification Tests (mocked OpenAI)
# ---------------------------------------------------------------------------

class TestClassification:
    """Test email classification with mocked API."""

    def test_classify_no_api_key(self, poller_module):
        with patch.object(poller_module, 'OPENAI_KEY', ''):
            msg = poller_module.EmailMessage(
                uid="1", from_addr="x@y.com", subject="Test", body="Hello"
            )
            result = poller_module.classify_email(msg)
            assert result.category == "unknown"
            assert result.confidence == 0.0

    def test_classify_success(self, poller_module):
        mock_response = json.dumps({
            "choices": [{"message": {"content": json.dumps({
                "category": "action-required",
                "confidence": 0.92,
                "draft": "Thanks for reaching out!",
                "reasoning": "Requests a meeting",
            })}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 50},
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response

        with patch.object(poller_module, 'OPENAI_KEY', 'sk-test'), \
             patch('urllib.request.urlopen', return_value=mock_resp):
            msg = poller_module.EmailMessage(
                uid="1", from_addr="partner@corp.com",
                subject="Partnership", body="Let's discuss..."
            )
            result = poller_module.classify_email(msg)
            assert result.category == "action-required"
            assert result.confidence == 0.92
            assert "reaching out" in result.draft

    def test_classify_api_error(self, poller_module):
        with patch.object(poller_module, 'OPENAI_KEY', 'sk-test'), \
             patch('urllib.request.urlopen', side_effect=Exception("timeout")):
            msg = poller_module.EmailMessage(
                uid="1", from_addr="x@y.com", subject="Test", body="Hello"
            )
            result = poller_module.classify_email(msg)
            assert result.category == "error"


# ---------------------------------------------------------------------------
# Telegram Notification Tests
# ---------------------------------------------------------------------------

class TestTelegramNotification:
    """Test notification formatting and sending."""

    def test_no_token_skips(self, poller_module):
        with patch.object(poller_module, 'TELEGRAM_TOKEN', ''):
            msg = poller_module.EmailMessage(
                uid="1", from_addr="x@y.com", subject="Test", body="Hello"
            )
            result_obj = poller_module.ClassificationResult(
                category="action-required", confidence=0.9
            )
            sent = poller_module.send_telegram_notification(msg, result_obj)
            assert sent is False

    def test_send_success(self, poller_module):
        mock_resp = MagicMock()
        mock_resp.status = 200

        with patch.object(poller_module, 'TELEGRAM_TOKEN', 'test-token'), \
             patch.object(poller_module, 'BOB_CHAT_ID', '12345'), \
             patch('urllib.request.urlopen', return_value=mock_resp):
            msg = poller_module.EmailMessage(
                uid="1", from_addr="partner@corp.com",
                subject="Meeting Request", body="Can we meet?",
                snippet="Can we meet?",
            )
            result_obj = poller_module.ClassificationResult(
                category="action-required", confidence=0.88,
                draft="Sure, let's meet!", reasoning="Requests meeting",
            )
            sent = poller_module.send_telegram_notification(msg, result_obj)
            assert sent is True

    def test_category_emoji_mapping(self, poller_module):
        assert poller_module.CATEGORY_EMOJI["action-required"] == "🔴"
        assert poller_module.CATEGORY_EMOJI["spam"] == "🗑️"
        assert poller_module.CATEGORY_EMOJI["newsletter"] == "📰"
        assert poller_module.CATEGORY_EMOJI["foundation-business"] == "🏛️"


# ---------------------------------------------------------------------------
# Poll Cycle Tests
# ---------------------------------------------------------------------------

class TestPollCycle:
    """Test the full poll_once cycle."""

    def test_poll_no_password(self, poller_module, tmp_data_dir):
        with patch.object(poller_module, 'IMAP_PASSWORD', ''), \
             patch.object(poller_module, 'SEEN_FILE', tmp_data_dir / "seen.json"), \
             patch.object(poller_module, 'DATA_DIR', tmp_data_dir):
            stats = poller_module.poll_once()
            assert stats.fetched == 0
            assert stats.classified == 0

    def test_poll_with_emails(self, poller_module, tmp_data_dir):
        mock_messages = [
            poller_module.EmailMessage(
                uid="msg_001", from_addr="alice@corp.com",
                subject="Urgent: Review needed", body="Please review the doc.",
            ),
            poller_module.EmailMessage(
                uid="msg_002", from_addr="newsletter@news.com",
                subject="Weekly Digest", body="This week in AI...",
            ),
        ]

        mock_classification_1 = poller_module.ClassificationResult(
            category="action-required", confidence=0.91,
            draft="I'll review it today.", reasoning="Requests review",
        )
        mock_classification_2 = poller_module.ClassificationResult(
            category="newsletter", confidence=0.97,
            reasoning="Newsletter format",
        )

        classifications = iter([mock_classification_1, mock_classification_2])

        with patch.object(poller_module, 'IMAP_PASSWORD', 'test'), \
             patch.object(poller_module, 'SEEN_FILE', tmp_data_dir / "seen.json"), \
             patch.object(poller_module, 'COST_LOG_FILE', tmp_data_dir / "costs.json"), \
             patch.object(poller_module, 'DATA_DIR', tmp_data_dir), \
             patch.object(poller_module, 'fetch_new_emails', return_value=mock_messages), \
             patch.object(poller_module, 'classify_email', side_effect=lambda m: next(classifications)), \
             patch.object(poller_module, 'send_telegram_notification', return_value=True):

            stats = poller_module.poll_once()
            assert stats.fetched == 2
            assert stats.classified == 2
            assert stats.action_required == 1
            assert stats.archived == 1

    def test_poll_skips_seen_uids(self, poller_module, tmp_data_dir):
        """Already-seen emails are not re-classified."""
        seen_file = tmp_data_dir / "seen.json"
        seen_file.write_text(json.dumps({"uids": ["msg_001"]}))

        mock_messages = [
            poller_module.EmailMessage(
                uid="msg_001", from_addr="alice@corp.com",
                subject="Old email", body="Already seen.",
            ),
            poller_module.EmailMessage(
                uid="msg_002", from_addr="bob@corp.com",
                subject="New email", body="Brand new.",
            ),
        ]

        mock_result = poller_module.ClassificationResult(
            category="FYI-only", confidence=0.85,
        )

        with patch.object(poller_module, 'IMAP_PASSWORD', 'test'), \
             patch.object(poller_module, 'SEEN_FILE', seen_file), \
             patch.object(poller_module, 'COST_LOG_FILE', tmp_data_dir / "costs.json"), \
             patch.object(poller_module, 'DATA_DIR', tmp_data_dir), \
             patch.object(poller_module, 'fetch_new_emails', return_value=mock_messages), \
             patch.object(poller_module, 'classify_email', return_value=mock_result), \
             patch.object(poller_module, 'send_telegram_notification', return_value=True):

            stats = poller_module.poll_once()
            # Only msg_002 should be classified (msg_001 already seen)
            assert stats.classified == 1


# ---------------------------------------------------------------------------
# Cost Data Generator Tests
# ---------------------------------------------------------------------------

class TestCostDataGenerator:
    """Test the generate_cost_data.py script."""

    def test_generate_empty(self, cost_gen_module, tmp_data_dir):
        cost_file = tmp_data_dir / "email_poll_costs.json"
        output_file = tmp_data_dir / "costs-data.json"

        with patch.object(cost_gen_module, 'COST_LOG_FILE', cost_file), \
             patch.object(cost_gen_module, 'OUTPUT_FILE', output_file):
            data = cost_gen_module.generate()
            assert data["summary"]["total_cost_usd"] == 0
            assert data["summary"]["total_classified"] == 0
            assert data["summary"]["projected_monthly_usd"] == 0
            assert data["polls"] == []

    def test_generate_with_data(self, cost_gen_module, tmp_data_dir):
        cost_file = tmp_data_dir / "email_poll_costs.json"
        output_file = tmp_data_dir / "costs-data.json"

        now = datetime.now(timezone.utc)
        entries = [
            {
                "timestamp": (now - timedelta(hours=i)).isoformat(),
                "fetched": 3,
                "classified": 2,
                "action_required": 1,
                "archived": 1,
                "errors": 0,
                "cost_usd": 0.000150,
            }
            for i in range(10)
        ]
        cost_file.write_text(json.dumps(entries))

        with patch.object(cost_gen_module, 'COST_LOG_FILE', cost_file), \
             patch.object(cost_gen_module, 'OUTPUT_FILE', output_file):
            data = cost_gen_module.generate()
            assert data["summary"]["total_cost_usd"] == pytest.approx(0.0015, abs=0.0001)
            assert data["summary"]["total_classified"] == 20
            assert data["summary"]["total_action_required"] == 10
            assert data["last_24h"]["classified"] == 20  # All within 24h
            assert data["summary"]["projected_monthly_usd"] > 0
            assert len(data["polls"]) == 10

    def test_generate_main_writes_file(self, cost_gen_module, tmp_data_dir):
        cost_file = tmp_data_dir / "email_poll_costs.json"
        output_file = tmp_data_dir / "costs-data.json"
        cost_file.write_text("[]")

        with patch.object(cost_gen_module, 'COST_LOG_FILE', cost_file), \
             patch.object(cost_gen_module, 'OUTPUT_FILE', output_file):
            cost_gen_module.main()
            assert output_file.exists()
            data = json.loads(output_file.read_text())
            assert "generated_at" in data
            assert "summary" in data


# ---------------------------------------------------------------------------
# Bot /costs Command Tests
# ---------------------------------------------------------------------------

class TestBotCostsCommand:
    """Test the /costs command uses the v2 CostTracker."""

    def test_cost_tracker_records(self):
        """CostTracker records and reports costs."""
        import tempfile
        from src.personal_foundation.v2.state import StateStore
        from src.personal_foundation.v2.cost_tracker import CostTracker

        tmp = tempfile.mkdtemp()
        s = StateStore(Path(tmp) / "test.db")
        ct = CostTracker(s)

        cost = ct.record("personal/email_classifier", "gpt-4o-mini", 500, 200)
        assert cost > 0

        report = ct.get_weekly_report()
        assert report["total_calls"] == 1
        assert report["total_cost"] > 0
        assert len(report["by_agent"]) == 1
        assert report["by_agent"][0]["agent"] == "personal/email_classifier"

    def test_cost_tracker_daily(self):
        """Daily cost report works."""
        import tempfile
        from src.personal_foundation.v2.state import StateStore
        from src.personal_foundation.v2.cost_tracker import CostTracker

        tmp = tempfile.mkdtemp()
        s = StateStore(Path(tmp) / "test.db")
        ct = CostTracker(s)

        ct.record("personal/writing_agent", "gpt-4o-mini", 1000, 500)
        ct.record("personal/email_classifier", "gpt-4o-mini", 300, 100)

        daily = ct.get_daily_cost()
        assert daily["total_calls"] == 2
        assert daily["total_cost"] > 0
        assert len(daily["by_agent"]) == 2


# ---------------------------------------------------------------------------
# IMAP Header Decoding Tests
# ---------------------------------------------------------------------------

class TestIMAPHelpers:
    """Test IMAP helper functions."""

    def test_decode_plain_header(self, poller_module):
        result = poller_module.decode_header_value("Simple Subject")
        assert result == "Simple Subject"

    def test_decode_encoded_header(self, poller_module):
        # RFC 2047 encoded header
        encoded = "=?utf-8?B?SGVsbG8gV29ybGQ=?="
        result = poller_module.decode_header_value(encoded)
        assert result == "Hello World"

    def test_extract_body_plain(self, poller_module):
        import email
        msg = email.message_from_string(
            "From: test@example.com\r\n"
            "Subject: Test\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "This is the body text."
        )
        body = poller_module.extract_body(msg)
        assert "This is the body text" in body

    def test_extract_body_truncates(self, poller_module):
        import email
        long_body = "x" * 2000
        msg = email.message_from_string(
            "From: test@example.com\r\n"
            "Subject: Test\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            + long_body
        )
        body = poller_module.extract_body(msg, max_chars=100)
        assert len(body) <= 100


# ---------------------------------------------------------------------------
# PollStats Tests
# ---------------------------------------------------------------------------

class TestPollStats:
    """Test PollStats dataclass."""

    def test_defaults(self, poller_module):
        stats = poller_module.PollStats()
        assert stats.fetched == 0
        assert stats.classified == 0
        assert stats.action_required == 0
        assert stats.archived == 0
        assert stats.errors == 0
        assert stats.cost_usd == 0.0
        assert stats.timestamp  # Should have a timestamp

    def test_custom_values(self, poller_module):
        stats = poller_module.PollStats(
            fetched=10, classified=8, action_required=3,
            archived=5, errors=0, cost_usd=0.001,
        )
        assert stats.fetched == 10
        assert stats.classified == 8
