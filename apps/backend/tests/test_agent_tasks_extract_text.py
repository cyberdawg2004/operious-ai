from __future__ import annotations

from app.workers.agent_tasks import _extract_text


def test_extract_text_merges_distinct_subject_and_body() -> None:
    """SES emails carry a distinct subject and body; both must reach diagnosis."""

    payload = {
        "subject": "PowerCore not charging",
        "text": (
            "I've tried two different cables and three wall adapters, and the "
            "LED indicator stays off completely."
        ),
        "channel": "email",
    }

    content = _extract_text(payload)

    assert "PowerCore not charging" in content
    assert "two different cables and three wall adapters" in content
    assert "LED indicator stays off" in content


def test_extract_text_subject_only() -> None:
    payload = {"subject": "PowerCore not charging"}

    assert _extract_text(payload) == "PowerCore not charging"


def test_extract_text_body_only() -> None:
    payload = {"text": "It won't turn on at all."}

    assert _extract_text(payload) == "It won't turn on at all."


def test_extract_text_comment_only_voice_channel() -> None:
    payload = {
        "channel": "voice",
        "comment": "Customer says the unit overheats during charging.",
    }

    assert _extract_text(payload) == (
        "Customer says the unit overheats during charging."
    )


def test_extract_text_smoke_fixture_subject_equals_comment() -> None:
    payload = {
        "subject": "Seeking help",
        "comment": "Seeking help",
    }

    assert _extract_text(payload) == "Seeking help"


def test_extract_text_empty_payload_falls_back_to_remaining_values() -> None:
    payload = {"channel": "email", "from": "customer@example.com"}

    content = _extract_text(payload)

    assert "email" in content
    assert "customer@example.com" in content
