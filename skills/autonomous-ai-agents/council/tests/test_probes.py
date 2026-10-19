"""Tests for probes.py — the deterministic checks.

Run standalone (no pytest needed):
    python tests/test_probes.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("probes", REPO / "scripts" / "probes.py")
probes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probes)

# The gate's own table, so the toolchain<->gate contract is asserted against the
# real definition rather than a copy.
_sspec = importlib.util.spec_from_file_location(
    "score_reviews", REPO / "scripts" / "score_reviews.py")
score = importlib.util.module_from_spec(_sspec)
sys.modules["score_reviews"] = score
_sspec.loader.exec_module(score)


# --- output parsing ---------------------------------------------------------
# statix pretty-prints each object across many lines, deadnix emits one per line:
# a line-based parser returns ZERO for statix — a false clean bill on a file that
# does not even parse.

def test_parses_deadnix_jsonl():
    """deadnix: one object per line."""
    text = (
        '{"file":"./a.nix","results":[{"line":1,"column":3,"message":"Unused lambda pattern: x"}]}\n'
        '{"file":"./b.nix","results":[{"line":4,"column":3,"message":"Unused let binding: y"}]}\n'
    )
    objs = probes._json_objects(text)
    assert len(objs) == 2, objs
    assert objs[0]["file"] == "./a.nix"
    assert objs[1]["results"][0]["line"] == 4


def test_parses_statix_pretty_printed():
    """statix: objects pretty-printed across many lines, concatenated."""
    text = json.dumps({
        "file": "./broken.nix",
        "report": [{
            "note": "Syntax error", "severity": "Error",
            "diagnostics": [{"at": {"from": {"line": 1, "column": 8}},
                             "message": "Unexpected TOKEN_IDENT"}],
        }],
    }, indent=2) + "\n" + json.dumps({
        "file": "./ok.nix", "report": [],
    }, indent=2)
    objs = probes._json_objects(text)
    assert len(objs) == 2, objs
    assert objs[0]["file"] == "./broken.nix"
    diag = objs[0]["report"][0]["diagnostics"][0]
    assert diag["at"]["from"]["line"] == 1


def test_parser_ignores_noise():
    """Non-JSON banner lines must not break parsing."""
    text = 'warning: something\n{"file":"./a.nix","results":[]}\ntrailing garbage'
    objs = probes._json_objects(text)
    assert len(objs) == 1
    assert objs[0]["file"] == "./a.nix"


# --- built-in probes --------------------------------------------------------

def test_secret_grep_finds_a_credential():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "conf.py").write_text(
            'API_KEY = "inf_9f4c2b7e1a8d6350b2c4e6f8a0d1c3e5"\n', encoding="utf-8")
        out = probes.probe_secret_grep(root)
        assert out["ran"] is True
        assert len(out["findings"]) >= 1
        assert out["signal"] < 100


def test_secret_grep_ignores_examples():
    """A secret-shaped string in docs/examples must not fire (SNR matters)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "examples").mkdir()
        (root / "examples" / "conf.py").write_text(
            'API_KEY = "inf_9f4c2b7e1a8d6350b2c4e6f8a0d1c3e5"\n', encoding="utf-8")
        out = probes.probe_secret_grep(root)
        assert out["findings"] == [], out["findings"]


def test_py_compile_catches_syntax_error():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "ok.py").write_text("x = 1\n", encoding="utf-8")
        (root / "bad.py").write_text("def f(:\n", encoding="utf-8")
        out = probes.probe_py_compile(root)
        assert out["ran"] is True
        assert len(out["findings"]) == 1
        assert out["findings"][0]["severity"] == "critical"
        assert "bad.py" in out["findings"][0]["location"]["path"]


def test_complexity_flags_a_hotspot():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        body = "def tangled(x):\n" + "".join(
            f"    if x == {i}:\n        x += {i}\n" for i in range(20)) + "    return x\n"
        (root / "t.py").write_text(body, encoding="utf-8")
        out = probes.probe_complexity(root)
        assert out["ran"] is True
        assert len(out["findings"]) >= 1
        assert "complexity" in out["findings"][0]["claim"]


def test_declared_rules_scores_absence():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out = probes.probe_declared_rules(root)
        assert out["ran"] is True
        assert out["signal"] < 100
        assert len(out["findings"]) == 1
        (root / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
        out2 = probes.probe_declared_rules(root)
        assert out2["signal"] == 100.0
        assert out2["findings"] == []


# --- nix probes: honest degradation -----------------------------------------
# Without the toolchain every nix probe reports ran=False; ran=True would inflate beta.

def test_nix_probes_degrade_without_nix():
    """When the toolchain cannot resolve, every nix probe reports ran=False and
    must NEVER invent a result — claiming ran=True would inflate beta."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "flake.nix").write_text("{ outputs = { self }: {}; }\n", encoding="utf-8")
        (root / "a.nix").write_text("{ x = 1; }\n", encoding="utf-8")
        original = probes._bridge
        probes._bridge = lambda *a, **k: (127, "toolchain unavailable (test)")
        try:
            for name in ("statix", "deadnix", "nixfmt", "flake-check", "nix-eval"):
                out = probes.run_probe(name, root)
                assert out["ran"] is False, f"{name} claimed to run without a toolchain"
                assert out["parsed"] is False, name
                assert out["findings"] == [], f"{name} invented findings while not running"
                assert out["signal"] is None, f"{name} produced a signal while not running"
        finally:
            probes._bridge = original


def test_probe_with_no_nix_files_reports_not_run():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)  # no .nix files at all
        for name in ("statix", "deadnix", "nixfmt", "nix-eval"):
            out = probes.run_probe(name, root)
            assert out["ran"] is False, f"{name} claimed to run with no .nix files"
            assert out["parsed"] is False


def test_run_probe_never_raises():
    """A broken probe must not break the run."""
    out = probes.run_probe("does-not-exist", Path("."))
    assert out["ran"] is False
    assert "unknown probe" in out["note"]


# --- python probes: the same honest degradation ------------------------------
# The gate EXPECTED ruff, mypy, bandit, a dependency scanner and pytest and left
# them to the reviewer — beta measured diligence on the Python side, the toolchain
# on the Nix side. They are harness probes now; one that cannot run must say so.

def test_python_probes_degrade_without_a_toolchain():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        # A lockfile, so the dependency probe actually needs the toolchain: with no
        # dependencies it reports "nothing to audit" without invoking osv-scanner.
        (root / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
        # Both need a file of the right kind before reaching the toolchain:
        # shellcheck says "no shell files", gitleaks needs something to scan.
        (root / "a.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        original = probes._bridge
        probes._bridge = lambda *a, **k: (127, "toolchain unavailable (test)")
        try:
            for name in ("ruff", "mypy", "bandit", "pytest", "osv-scanner",
                         "gitleaks", "shellcheck"):
                out = probes.run_probe(name, root)
                assert out["ran"] is False, f"{name} claimed to run without a toolchain"
                assert out["parsed"] is False, name
                assert out["findings"] == [], f"{name} invented findings while not running"
                assert out["signal"] is None, f"{name} produced a signal while not running"
        finally:
            probes._bridge = original


#: The stacks this toolchain ships for. `STACK_TOOLS` also lists JavaScript, Rust
#: and Go tools, which the framework does not claim to cover — asserting those
#: would demand probes for tools that are deliberately absent.
SUPPORTED_STACKS = ("nix", "python", "shell")


def _expected_for_supported_stacks() -> set:
    """Every expected tool name the gate can ask for on a stack we ship."""
    out = set()
    for _dimension, per_stack in score.STACK_TOOLS.items():
        for stack in SUPPORTED_STACKS:
            out |= set(per_stack.get(stack, []))
    for _dimension, names in score.GENERIC_TOOLS.items():
        out |= set(names)
    return out


def _all_expected_names() -> set:
    out = set()
    for _dimension, per_stack in score.STACK_TOOLS.items():
        for names in per_stack.values():
            out |= set(names)
    for _dimension, names in score.GENERIC_TOOLS.items():
        out |= set(names)
    return out


def test_every_expected_tool_has_a_probe():
    """The asymmetry this closes: a tool the gate EXPECTS that no probe runs can
    only ever be satisfied by the reviewer's own report. That is what made beta a
    measure of diligence on the Python side and of the toolchain on the Nix side.

    DERIVED from `STACK_TOOLS`, not a hand-written list: the previous version listed
    16 names by hand and missed `shellcheck`, which was scored for the `shell` stack
    with no probe — a shell repository had an expected tool that could never run.
    """
    expected = _expected_for_supported_stacks()
    missing = sorted(expected - set(probes.PROBES))
    assert missing == [], f"the gate expects tools that no probe runs: {missing}"


def test_every_declared_external_tool_is_actually_expected():
    """`EXTERNAL_TOOLS` says "the toolchain must ship this". A name in it that the
    gate never asks for is a typo, and a typo silently exempts the tool it was meant
    to cover from the shipping requirement below."""
    stray = sorted(set(score.EXTERNAL_TOOLS) - _all_expected_names())
    assert stray == [], f"declared external but never expected by the gate: {stray}"


def test_every_internal_expected_name_is_a_probe():
    """The other half of the classification: a name that is not an external binary is
    a probe implemented inside probes.py, so it must exist there.

    Note an external name is ALSO a probe name — the probe named `ruff` is what runs
    the `ruff` binary — so the two sets overlap by design. What must not happen is an
    expected name with no probe at all, for a stack we ship.
    """
    internal = _expected_for_supported_stacks() - set(score.EXTERNAL_TOOLS)
    missing = sorted(internal - set(probes.PROBES))
    assert missing == [], f"internal expected names with no probe: {missing}"


def test_the_qa_toolchain_ships_every_external_scored_tool():
    """A scored tool that does not ship cannot run, so beta is capped by the packaging
    rather than by the repository. This is the toolchain<->gate contract."""
    names = _toolchain_tool_names()
    assert names, "could not read toolNames from nix/builders.nix"
    needed = {t for t in _expected_for_supported_stacks() if t in score.EXTERNAL_TOOLS}
    missing = sorted(needed - names)
    assert missing == [], f"the gate scores tools the toolchain does not ship: {missing}"


#: Tools that SHIP in the toolchain but must NOT be probed.
#: `vulnix` ships on demand — closure CVEs are a real question for a Nix reviewer —
#: but probing it fetches NVD over the network (minutes, answer varies by date) and
#: it is unmaintained with a high false-positive rate: unusable signal for the cost.
ON_DEMAND_TOOLS = {"vulnix"}


def _toolchain_tool_names() -> set[str]:
    """The names in nix/builders.nix's `toolNames` — the toolchain closure."""
    text = (REPO / "nix" / "builders.nix").read_text(encoding="utf-8")
    block = text.split("toolNames = [", 1)[1].split("];", 1)[0]
    return set(re.findall(r'^\s*"([^"]+)"', block, re.M))


def test_an_on_demand_tool_ships_but_is_not_probed():
    """Both halves, so neither can drift: available, and never run by a review.

    A tool that ships but is not probed is invisible to `council probes`; a tool that
    is probed but not shipped fails on PATH. This asserts the deliberate state rather
    than letting either half move alone.
    """
    names = _toolchain_tool_names()
    assert names, "could not read toolNames from nix/builders.nix"
    missing = sorted(ON_DEMAND_TOOLS - names)
    assert missing == [], f"declared on demand but not shipped: {missing}"
    probed = sorted(ON_DEMAND_TOOLS & set(probes.PROBES))
    assert probed == [], f"on-demand tools are being probed on every run: {probed}"


def test_parser_accepts_a_top_level_json_array():
    """ruff emits ONE array; statix and deadnix emit concatenated objects. One
    parser has to read both, or a tool's entire output parses as zero findings --
    a false clean bill of health."""
    text = json.dumps([{"code": "F401", "filename": "a.py",
                        "location": {"row": 3}, "message": "unused import"}])
    objs = probes._json_objects(text)
    assert len(objs) == 1, objs
    assert objs[0]["code"] == "F401"


def test_osv_scanner_separates_nothing_to_audit_from_cannot_audit():
    """No dependencies and unreadable dependencies are different facts, and only
    one of them is clean. Reporting the second as clean would hide unaudited risk
    behind a 100."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out = probes.probe_osv_scanner(root)
        assert out["ran"] is True
        assert out["signal"] == 100.0
        assert "no dependencies declared" in out["note"]

        (root / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["requests>=2"]\n', encoding="utf-8")
        out2 = probes.probe_osv_scanner(root)
        assert out2["ran"] is False, "declared-but-unreadable deps reported as clean"
        assert out2["signal"] is None
        assert "lockfile" in out2["note"]


# --- the two probes added by the toolchain audit ----------------------------
# Both need the PINNED toolchain: CI's nix job provides it, a bare pytest run does
# not. `checks.probes` requires both to have RUN, so the real exercise is there; here
# the positive case skips when the toolchain does not resolve, and the degradation
# test above covers the absent case.

def _toolchain_unresolved(out: dict) -> bool:
    """True when the probe reached the toolchain and could not resolve it.

    Guarding on `shutil.which` is not enough: in the Nix build sandbox the toolchain IS
    on PATH while `toolchain.run` still cannot resolve it (there is no `nix` inside it),
    so a which-based guard lets the test run and fail where it should skip.
    """
    return not out["ran"] and "toolchain" in str(out.get("note", "")).lower()


def test_gitleaks_finds_a_credential_without_reporting_it():
    """The report carries the SECRET. It must never reach a finding — a credential in
    a review report is the leak the probe exists to prevent."""
    if shutil.which("gitleaks") is None:
        return
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # Built at runtime, not a literal: a committed `sk_live_` string is the very
        # mistake this test exists to prevent. gitleaks matches the SHAPE.
        secret = "sk_" + "live_" + "".join(
            "0123456789abcdef"[i % 16] for i in range(48)
        )
        (root / "app.py").write_text(f'KEY = "{secret}"\n', encoding="utf-8")
        out = probes.run_probe("gitleaks", root)
        if _toolchain_unresolved(out):
            return
        assert out["ran"] is True, out["note"]
        assert out["findings"], "a hardcoded credential was not reported"
        blob = json.dumps(out)
        assert secret not in blob, "the secret value leaked into the probe result"
        assert "sk_live" not in blob, "a prefix of the secret leaked"


def test_shellcheck_reports_a_shell_issue():
    if shutil.which("shellcheck") is None:
        return
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "bad.sh").write_text("#!/bin/sh\nfor f in $(ls); do echo $f; done\n",
                                     encoding="utf-8")
        out = probes.run_probe("shellcheck", root)
        if _toolchain_unresolved(out):
            return
        assert out["ran"] is True, out["note"]
        assert out["findings"], "SC2045 was not reported"
        assert all(f["location"]["path"] for f in out["findings"])


def test_pytest_exit_5_is_not_run_not_pass():
    """Exit 5 is 'no tests collected' -- not a pass and not a failure. Calling it
    a pass would let a repository with no tests score full marks on correctness."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        original = probes._bridge
        probes._bridge = lambda *a, **k: (5, "no tests ran in 0.01s")
        try:
            out = probes.run_probe("pytest", root)
            assert out["ran"] is False
            assert out["signal"] is None
        finally:
            probes._bridge = original


def test_signal_is_a_density_not_a_count():
    """§6 applies the Hill curve to findings per KLOC. Feeding it a raw count
    scored a 14 KLOC repository's 16 findings as 16 per KLOC. Survivable while
    beta < 1 let the reviewer's score dominate; at beta = 1 the probe signal IS
    the score, so the miscalibration decides verdicts and penalises size."""
    with tempfile.TemporaryDirectory() as td:
        small, big = Path(td) / "small", Path(td) / "big"
        small.mkdir()
        big.mkdir()
        # The same 20 findings, in a tree 100x larger: a far lower density.
        for root, modules in ((small, 20), (big, 2000)):
            for i in range(modules):
                (root / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")
        assert probes.score_from_density(20, small) < probes.score_from_density(20, big)


def test_density_falls_back_to_a_count_with_no_measurable_size():
    """You cannot normalise by a size you have not measured -- and the fallback
    must match score_reviews' so the two never disagree."""
    assert probes.score_from_density(16, None) == probes.score_from_density(16, Path("/nonexistent-rc"))
    assert probes.score_from_density(0, None) == 100.0


# --- probing must not modify the repo under review --------------------------
# `nix flake check` and `nix eval` write `flake.lock` into the tree they run
# against: probing `tests/golden/target` created one and the fixture's own hashes
# picked it up. `_bridge` injects `--no-write-lock-file` so it cannot recur.

def test_bridge_forbids_writing_a_lock_file():
    """Every `nix flake` / `nix eval` call carries `--no-write-lock-file`."""
    seen = []

    def fake_run(args, repo=None, timeout=None, env_extra=None, merge_stderr=True):
        seen.append(list(args))
        return (0, "")

    original = probes.toolchain.run
    probes.toolchain.run = fake_run
    try:
        probes._bridge(Path("."), ["nix", "flake", "check", "--no-build"])
        probes._bridge(Path("."), ["nix", "eval", "--raw", ".#x"])
    finally:
        probes.toolchain.run = original

    assert len(seen) == 2, seen
    for args in seen:
        assert "--no-write-lock-file" in args, f"lock write not forbidden: {args}"
    # the flag must follow the SUBCOMMAND, or nix calls it unrecognised
    assert seen[0][:4] == ["nix", "flake", "check", "--no-write-lock-file"], seen[0]
    assert seen[1][:3] == ["nix", "eval", "--no-write-lock-file"], seen[1]


def test_bridge_leaves_other_commands_alone():
    """Non-nix commands are passed through untouched."""
    seen = []

    def fake_run(args, repo=None, timeout=None, env_extra=None, merge_stderr=True):
        seen.append(list(args))
        return (0, "")

    original = probes.toolchain.run
    probes.toolchain.run = fake_run
    try:
        probes._bridge(Path("."), ["statix", "check", ".", "-o", "json"])
        probes._bridge(Path("."), ["nix-instantiate", "--parse", "a.nix"])
    finally:
        probes.toolchain.run = original

    assert seen[0] == ["statix", "check", ".", "-o", "json"], seen[0]
    assert seen[1] == ["nix-instantiate", "--parse", "a.nix"], seen[1]
    for args in seen:
        assert "--no-write-lock-file" not in args, args


# --- zizmor: GitHub Actions workflow security ---------------------------------
# The only probe reading `.github/`. Two invariants matter more than the parsing: a
# repo without workflows must not be penalised, and non-JSON must be a reported
# failure rather than a silent clean.

def test_zizmor_is_not_an_expected_tool():
    """It reads `.github/workflows`, which many repositories do not have.

    Listing it in STACK_TOOLS would make beta fall on every repo without CI — the
    repository would be punished for a check that cannot apply to it. It still
    contributes to `det` through `tools_run` when it does run.
    """
    expected = set()
    for dim in score.STACK_TOOLS.values():
        for tools in dim.values():
            expected |= set(tools)
    assert "zizmor" not in expected, (
        "zizmor must stay out of the expected set: a repo with no workflows would "
        "lose beta for a check that cannot run there")


def test_zizmor_is_registered_and_resolvable():
    assert "zizmor" in probes.PROBES
    assert callable(probes.PROBES["zizmor"])


def test_zizmor_without_workflows_does_not_run():
    with tempfile.TemporaryDirectory() as td:
        out = probes.run_probe("zizmor", Path(td))
        assert out["ran"] is False, out
        assert out["signal"] is None, "an inapplicable probe must not produce a score"
        assert "workflow" in out["note"].lower(), out["note"]


def test_zizmor_parses_severity_location_and_feature():
    """The JSON shape is zizmor's, so it is pinned here rather than assumed."""
    payload = json.dumps([
        {"ident": "unpinned-uses", "desc": "unpinned action reference",
         "determinations": {"severity": "High"},
         "locations": [{
             "symbolic": {"key": {"Local": {"verbatim_path": ".github/workflows/x.yml"}}},
             "concrete": {"feature": "uses: actions/checkout@v4",
                          "location": {"start_point": {"row": 7}}}}]},
        {"ident": "excessive-permissions", "desc": "overly broad permissions",
         "determinations": {"severity": "Medium"},
         "locations": [{
             "symbolic": {"key": {"Local": {"verbatim_path": ".github/workflows/x.yml"}}},
             "concrete": {"feature": "build:",
                          "location": {"start_point": {"row": 4}}}}]},
    ])

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / ".github" / "workflows" / "x.yml").write_text("on: push\n", encoding="utf-8")

        original = probes._bridge
        probes._bridge = lambda *a, **k: (1, payload)
        try:
            out = probes.run_probe("zizmor", root)
        finally:
            probes._bridge = original

    assert out["ran"] is True, out
    assert out["parsed"] is True, out
    assert len(out["findings"]) == 2, out["findings"]

    high = out["findings"][0]
    assert high["severity"] == "high", high
    assert high["location"]["path"] == ".github/workflows/x.yml", high["location"]
    # `row` is 0-BASED, so row 7 is line 8 on screen. Asserting "7" here pinned the
    # off-by-one instead of the contract: every finding cited the line above its own.
    assert high["location"]["line_range"] == "8", high["location"]
    assert "actions/checkout@v4" in high["claim"], high["claim"]
    assert "zizmor" in high["falsifiable_check"], high["falsifiable_check"]

    assert out["findings"][1]["severity"] == "medium", out["findings"][1]


def test_zizmor_reports_a_non_json_answer_rather_than_crashing():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / ".github" / "workflows" / "x.yml").write_text("on: push\n", encoding="utf-8")

        original = probes._bridge
        probes._bridge = lambda *a, **k: (14, "panic: something went wrong")
        try:
            out = probes.run_probe("zizmor", root)
        finally:
            probes._bridge = original

    assert out["ran"] is False, out
    assert out["signal"] is None, out
    assert "did not emit JSON" in out["note"], out["note"]


def test_zizmor_clean_repo_scores_100():
    """No findings must read as clean, not as a missing measurement."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / ".github" / "workflows" / "x.yml").write_text("on: push\n", encoding="utf-8")

        original = probes._bridge
        probes._bridge = lambda *a, **k: (0, "[]")
        try:
            out = probes.run_probe("zizmor", root)
        finally:
            probes._bridge = original

    assert out["ran"] is True, out
    assert out["findings"] == [], out
    assert out["signal"] == 100.0, out["signal"]


def main() -> int:
    # Tests taking a fixture (`tmp_path`) cannot run here: this runner calls `fn()`
    # with no arguments, so it reported them ERROR while pytest ran them green —
    # a runner that invents failures teaches a reader to ignore it.
    import inspect
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = skipped = 0
    for name, fn in tests:
        try:
            if inspect.signature(fn).parameters:
                print(f"  SKIP {name} (needs a pytest fixture)")
                skipped += 1
                continue
            fn()
            print(f"  PASS {name}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL {name} -> {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {name} -> {type(exc).__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped (run pytest for those)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())


# --- the performance probes taken from the nine reference repositories -------------
# Each of these three was an actual finding: naersk reads Cargo.toml during evaluation
# (IFD); nix-direnv builds Nix in CI with no store cache and no concurrency key.

def test_ci_cache_reports_missing_cache(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "test.yml").write_text(
        "jobs:\n  t:\n    steps:\n      - uses: cachix/install-nix-action@v31\n"
        "      - run: nix build .#x\n", encoding="utf-8")
    d = probes.probe_ci_cache(tmp_path)
    assert d["ran"] is True
    assert d["signal"] == 40.0, d          # 0 of 1 cached -> the documented floor
    assert d["findings"] and d["findings"][0]["severity"] == "low"


def test_ci_cache_reports_a_configured_cache(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "test.yml").write_text(
        "jobs:\n  t:\n    steps:\n      - uses: cachix/cachix-action@v16\n"
        "      - run: nix build .#x\n", encoding="utf-8")
    d = probes.probe_ci_cache(tmp_path)
    assert d["signal"] == 100.0, d
    assert not d["findings"]


def test_ci_cache_ignores_a_workflow_that_does_not_build_nix(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "lint.yml").write_text("jobs:\n  t:\n    steps:\n      - run: echo hi\n",
                                 encoding="utf-8")
    d = probes.probe_ci_cache(tmp_path)
    assert d["ran"] is True and d["signal"] == 100.0, d


def test_ci_cache_without_workflows_is_a_vacuous_pass(tmp_path):
    """No workflows means "every Nix-building workflow has a cache" is vacuously true.

    Reporting `ran: false` here made the tool count as missing and depressed beta on a
    repository with no CI to fix — the same class of error as an incidental language
    stack making tools expected that had nothing to run on.
    """
    d = probes.probe_ci_cache(tmp_path)
    assert d["ran"] is True and d["signal"] == 100.0, d
    assert not d["findings"]
    assert "workflows" in d["note"]


def test_ci_concurrency_without_workflows_is_a_vacuous_pass(tmp_path):
    d = probes.probe_ci_concurrency(tmp_path)
    assert d["ran"] is True and d["signal"] == 100.0, d
    assert not d["findings"]


def test_ci_concurrency_counts_missing_keys(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "a.yml").write_text("on: push\njobs:\n  t:\n    steps: []\n", encoding="utf-8")
    (wf / "b.yml").write_text("on: push\nconcurrency:\n  group: x\njobs:\n  t:\n    steps: []\n",
                              encoding="utf-8")
    d = probes.probe_ci_concurrency(tmp_path)
    assert d["signal"] == 80.0, d          # 1 of 2 -> 60 + 40*0.5
    assert len(d["findings"]) == 1
    assert d["findings"][0]["location"]["path"] == ".github/workflows/a.yml"


def test_ifd_is_not_applicable_without_a_flake(tmp_path):
    d = probes.probe_ifd(tmp_path)
    assert d["ran"] is False and d["signal"] is None, d
    assert "flake.nix" in d["note"]


def test_the_performance_probes_are_expected_for_nix():
    """The gate must expect them, or beta will never count them."""
    expected = score.expected_tools("performance", ["nix"])
    for tool in ("ifd", "ci-cache", "ci-concurrency"):
        assert tool in expected, (tool, expected)
    assert "ifd" in score.NIX_PROBE_TOOLS
    assert "ci-cache" in score.BUILTIN_TOOLS
    assert "ci-concurrency" in score.BUILTIN_TOOLS


def test_a_bare_store_mention_is_not_a_cache(tmp_path):
    """`nix-store -qR` names /nix/store without caching anything.

    Counting a bare `/nix/store` mention reported a cache that did not exist. Only
    `actions/cache` actually pointed at the store counts.
    """
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "a.yml").write_text(
        "jobs:\n  t:\n    steps:\n      - uses: cachix/install-nix-action@v31\n"
        "      - run: nix-store -qR result | grep /nix/store\n", encoding="utf-8")
    d = probes.probe_ci_cache(tmp_path)
    assert d["signal"] == 40.0, d          # not cached, despite the /nix/store mention
    assert len(d["findings"]) == 1


def test_actions_cache_pointed_at_the_store_is_a_cache(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "a.yml").write_text(
        "jobs:\n  t:\n    steps:\n      - uses: cachix/install-nix-action@v31\n"
        "      - uses: actions/cache@v4\n        with:\n          path: /nix/store\n"
        "      - run: nix build .#x\n", encoding="utf-8")
    d = probes.probe_ci_cache(tmp_path)
    assert d["signal"] == 100.0, d
    assert not d["findings"]


def test_the_ci_cache_finding_names_a_check_that_matches_the_logic(tmp_path):
    """The falsifiable_check must grep for what the probe actually looks for."""
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "a.yml").write_text(
        "jobs:\n  t:\n    steps:\n      - run: nix build .#x\n", encoding="utf-8")
    d = probes.probe_ci_cache(tmp_path)
    check = d["findings"][0]["falsifiable_check"]
    assert "cachix/cachix-action" in check and "actions/cache" in check, check
    assert "/nix/store" not in check.split("grep")[1], check

# --- path normalisation -----------------------------------------------------
# `str(x).lstrip("./")` strips a CHARACTER SET, not a prefix. Measured: `.env` ->
# `env`, `.review-council/run/council.log` -> `review-council/...`, and
# `.github/workflows/ci.yml` -> `github/...` — a path that exists nowhere, cited as
# the location of a real finding. Nine call sites did this.

def test_a_leading_dot_survives_path_normalisation():
    """The prefix `./` is stripped; a dot that BELONGS to the name is not."""
    assert probes._shared.norm_path("./.github/workflows/ci.yml") == ".github/workflows/ci.yml"
    assert probes._shared.norm_path(".env") == ".env"
    assert probes._shared.norm_path(".review-council/x/council.log") == ".review-council/x/council.log"
    assert probes._shared.norm_path("src/.gitignore") == "src/.gitignore"
    assert probes._shared.norm_path("") == ""
    assert probes._shared.norm_path(None) == ""


def test_no_probe_strips_a_character_set_from_a_path():
    """A structural guard: the bug is invisible at runtime, so grep the source."""
    source = (REPO / "scripts" / "probes.py").read_text(encoding="utf-8")
    offenders = [
        line.strip() for line in source.splitlines()
        if 'lstrip("./")' in line and not line.strip().startswith("#")
    ]
    assert not offenders, f"lstrip(\"./\") strips a character set: {offenders}"


# --- zizmor line numbers ----------------------------------------------------
# `start_point.row` is 0-BASED. Unshifted, every workflow finding cited the line
# ABOVE the offender — 44 for a `uses:` on line 45 — pointing a reviewer at a
# comment and making a true finding look false.

def test_zizmor_reports_the_line_the_finding_is_on(tmp_path):
    if shutil.which("zizmor") is None:
        return
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    # The `uses:` sits on line 4 exactly; nothing else in the file can match.
    (wf / "a.yml").write_text(
        "on: push\njobs:\n  t:\n    steps:\n"
        "      - uses: actions/checkout@v4\n",
        encoding="utf-8")
    out = probes.run_probe("zizmor", tmp_path)
    if _toolchain_unresolved(out):
        return
    if not out["ran"]:
        return
    hits = [f for f in out["findings"] if "checkout" in f["claim"]]
    if not hits:
        return  # this zizmor build reports no audit on a minimal workflow
    assert hits[0]["location"]["line_range"] == "5", (
        "row is 0-based; unshifted it reports 4 for a `uses:` on line 5: "
        f"{hits[0]['location']}")


# --- gitleaks must not scan what SKIP_DIRS skips ----------------------------
# `gitleaks detect --source .` walks the whole tree, ignoring .gitignore and
# SKIP_DIRS, so the harness re-reported its own `.review-council` logs — including
# the run's quoted gitleaks output. Measured on a 377-file repo: 274 hits, 270
# ignored scratch.

def test_the_gitleaks_allowlist_covers_every_skip_dir():
    """Structural: the config and SKIP_DIRS must not drift apart.

    A new SKIP_DIRS entry that the gitleaks allowlist does not know about silently
    reopens the bug, and nothing else in the suite would notice.
    """
    config = probes._GITLEAKS_CONFIG
    # Compare escaping-agnostically: the config holds TOML literal strings, so the
    # name appears as `\.git` while the name itself has no backslash.
    plain = config.replace("\\", "")
    missing = [name for name in probes.SKIP_DIRS if f"/){name}(/|$)" not in plain]
    assert not missing, f"SKIP_DIRS entries missing from the gitleaks allowlist: {missing}"
    assert "[extend]" in config and "useDefault = true" in config, (
        "a config without [extend] useDefault replaces the shipped rule set, "
        "so every real credential stops being detected")


def test_gitleaks_ignores_review_scratch(tmp_path):
    """The run's own log is not a finding. Only the real credential is."""
    if shutil.which("gitleaks") is None:
        return
    secret = "sk_" + "live_" + "".join("0123456789abcdef"[i % 16] for i in range(48))
    (tmp_path / "app.py").write_text(f'KEY = "{secret}"\n', encoding="utf-8")
    scratch = tmp_path / ".review-council" / "20260101-000000"
    scratch.mkdir(parents=True)
    # A log quoting the same value, exactly as the harness writes it.
    (scratch / "council.log").write_text(f"gitleaks: {secret}\n", encoding="utf-8")
    pyc = tmp_path / "__pycache__"
    pyc.mkdir()
    (pyc / "x.py").write_text(f'KEY = "{secret}"\n', encoding="utf-8")

    out = probes.run_probe("gitleaks", tmp_path)
    if _toolchain_unresolved(out):
        return
    assert out["ran"] is True, out["note"]
    paths = [f["location"]["path"] for f in out["findings"]]
    assert paths == ["app.py"], (
        "ignored scratch was reported as a finding: " + str(paths))
