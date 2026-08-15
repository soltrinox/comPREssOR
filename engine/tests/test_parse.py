from pathlib import Path

from chat_compressor.parse import parse_jsonl, sanitize_text, turns_to_raw_text

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic-generic.jsonl"


def test_parse_synthetic_eight_turns() -> None:
    turns = parse_jsonl(FIXTURE)
    assert len(turns) == 8
    assert turns[0].role == "user"
    assert "buy groceries" in turns[0].text
    assert turns[-1].role == "assistant"


def test_sanitize_redacts_email_key_home() -> None:
    raw = "mail me@x.com key cursor_abcdefghijk path " + "/" + "Users" + "/alice/secret"
    out = sanitize_text(raw)
    assert "<EMAIL>" in out
    assert "<KEY>" in out
    assert "<HOME>" in out
    assert "me@x.com" not in out
    assert "cursor_abcdefghijk" not in out
    assert "/" + "Users" + "/alice" not in out


def test_sanitize_redacts_linux_home_prefix() -> None:
    out = sanitize_text("see /home/alice/secret and " + "/" + "Users" + "/bob/notes")
    assert "<HOME>" in out
    assert "/home/alice" not in out
    assert "/" + "Users" + "/bob" not in out


def test_raw_text_includes_roles() -> None:
    turns = parse_jsonl(FIXTURE)
    blob = turns_to_raw_text(turns)
    assert blob.startswith("user:")
    assert "assistant:" in blob
