"""Contract tests for the harness-audit plugin.

The plugin is exercised end-to-end against a real agent session in
`scripts/verify-live.py`; this file covers the part that must hold before that run can
mean anything — the records it writes, and the fact that it writes no prompt text.

Import by path, not by name: the plugin directory is `plugins/harness-audit`, which is
not an identifier, and the module is loaded by Hermes from a file path too.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
MODULE = REPO / "plugins" / "harness-audit" / "harness_audit.py"

PROMPT = "SYSTEM PROMPT SENTINEL — this text must never reach the log"
SECRET = "sk-abcdefghijklmnopqrstuvwx"


def load():
    spec = importlib.util.spec_from_file_location("harness_audit_under_test", MODULE)
    assert spec and spec.loader, f"cannot load {MODULE}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return load()


def request_kwargs(**over):
    kw = {
        "session_id": "sess-1",
        "task_id": "task-1",
        "turn_id": "turn-1",
        "api_request_id": "req-1",
        "platform": "cli",
        "provider": "custom",
        "model": "deepseek-v4.1-flash",
        "api_mode": "openai_chat",
        "api_call_count": 2,
        "retry_count": 0,
        "message_count": 12,
        "tool_count": 30,
        "approx_input_tokens": 4096,
        "request_char_count": 16384,
        "system_prompt": PROMPT,
    }
    kw.update(over)
    return kw


def test_a_request_is_recorded_as_sizes_and_a_digest_never_as_text(plugin):
    record = plugin._request_record(request_kwargs())
    assert record["messages"] == 12
    assert record["tools"] == 30
    assert record["approx_input_tokens"] == 4096
    assert record["system_prompt_bytes"] == len(PROMPT.encode("utf-8"))
    assert record["system_prompt_sha256"] == hashlib.sha256(PROMPT.encode()).hexdigest()[:16]
    # The whole record, serialised: the prompt must not be in it in any form.
    assert "SENTINEL" not in json.dumps(record)


def test_an_absent_system_prompt_is_none_not_zero_and_not_an_empty_digest(plugin):
    record = plugin._request_record(request_kwargs(system_prompt=None))
    assert record["system_prompt_bytes"] is None
    assert record["system_prompt_sha256"] is None
    # ...and an empty string is the same fact, not a prompt of zero bytes.
    empty = plugin._request_record(request_kwargs(system_prompt=""))
    assert empty["system_prompt_bytes"] is None


def test_the_hook_writes_one_line_per_request_and_the_file_holds_no_prompt_text(plugin):
    plugin.on_pre_api_request(**request_kwargs())
    plugin.on_pre_api_request(**request_kwargs(api_request_id="req-2", approx_input_tokens=8192))

    files = sorted((pathlib.Path(plugin._home()) / "logs" / "model-requests").glob("*.jsonl"))
    assert len(files) == 1, f"expected one day file, got {files}"
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "SENTINEL" not in files[0].read_text(encoding="utf-8")
    assert [json.loads(x)["request"] for x in lines] == ["req-1", "req-2"]


def test_the_summary_reports_growth_and_names_the_facts_it_did_not_get(plugin):
    records = [
        plugin._request_record(request_kwargs(approx_input_tokens=1000)),
        plugin._request_record(request_kwargs(approx_input_tokens=3000)),
    ]
    summary = plugin._summarize_requests(records)
    assert summary["requests"] == 2
    assert summary["complete"] is True
    assert summary["input_tokens"] == {"min": 1000, "median": 3000, "max": 3000, "growth": 2000}

    # Negative control: a host that did not report a size must not read as measured.
    partial = plugin._summarize_requests(records + [plugin._request_record(
        request_kwargs(approx_input_tokens=None))])
    assert partial["complete"] is False
    assert partial["tokens_missing"] == 1


def test_the_requests_action_reads_back_what_the_hook_wrote(plugin):
    plugin.on_pre_api_request(**request_kwargs())
    report = json.loads(plugin._audit({"action": "requests"}))
    assert report["summary"]["requests"] == 1
    assert report["summary"]["complete"] is True
    assert report["entries"][0]["model"] == "deepseek-v4.1-flash"
    assert "SENTINEL" not in json.dumps(report)


def test_an_unknown_action_names_the_actions_that_exist(plugin):
    report = json.loads(plugin._audit({"action": "nope"}))
    assert report["error"].startswith("unknown action")
    assert "requests" in report["actions"]


def test_credentials_are_redacted_by_key_and_by_shape(plugin):
    redacted = plugin._redact({"api_key": "plain", "path": "/tmp/x", "note": SECRET})
    assert redacted["api_key"] == "<redacted>"
    assert redacted["path"] == "/tmp/x"
    assert redacted["note"] == "<redacted:credential-shaped>"
