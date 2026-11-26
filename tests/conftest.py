"""Suite-wide policy: a skip is not a pass.

`tests/e2e/test_shipped_code.py` already states the rule for itself — "a `return` here
would be a pass that measured nothing". It skips when no host binary is on PATH, which
is right for a developer and wrong for the gate: the gate runs with
`HERMES_SKILLS_STRICT_SKIPS=1`, where a skip turns the check red and names itself.
"""

from __future__ import annotations

import os


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001, ARG001 - pytest hook
    if os.environ.get("HERMES_SKILLS_STRICT_SKIPS") != "1":
        return
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    skipped = list(getattr(reporter, "stats", {}).get("skipped", [])) if reporter else []
    if not skipped:
        return
    print(f"\n{len(skipped)} test(s) skipped; a skip is not a pass:")
    for report in skipped:
        reason = report.longrepr
        if isinstance(reason, tuple) and len(reason) == 3:
            reason = reason[2]
        print(f"  {report.nodeid}: {reason}")
    session.exitstatus = 1
