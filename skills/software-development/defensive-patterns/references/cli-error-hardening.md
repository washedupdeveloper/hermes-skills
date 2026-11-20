# CLI error hardening — probe matrix and fixes

Use this when a command-line tool must fail fast and never leave debris. The
sequence is: inventory the surface, probe it as a black box, fix at the boundary,
then pin each class with a regression.

## When to Use

- A CLI accepts paths, revisions, ids, config files or subprocess names.
- A bad invocation currently produces a traceback, a wrong exit code, a silent
  no-op, or a run directory that survives the failure.
- A refactor moved a guard and the mutation/regression suite no longer exercises it.
- Not for a pure library with no I/O boundary; test its typed errors directly.

## 1. Inventory the surface

Read the parser and list every place a user value crosses into a side effect.

- Every subcommand, positional, flag, `type=`, `choices`, `append` and default.
- Every `Path` value and every place it is joined, opened or `mkdir`ed.
- Every subprocess (`cwd`, binary, argv, timeout) and every parser (`tomllib`,
  `json`, a custom prompt/config reader).
- Every output destination (`--sarif`, `--keep`, report path) and its parent.
- Every exit path: pass, fail, incomplete, start failure, usage error.

## 2. Probe as a black box

Use a temporary git repository, a stub reviewer/analyzer, and no live model or
network. Capture exit code, whether the output contains `Traceback`, and the last
line of stderr.

```python
import subprocess

def probe(label: str, argv: list[str]) -> tuple[str, int, bool, str]:
    run = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=60)
    text = run.stdout + run.stderr
    last = (run.stderr or run.stdout).strip().splitlines()
    return label, run.returncode, "Traceback" in text, last[-1] if last else ""
```

Run the valid invocation first; every invalid case is compared against it.

## 3. Matrix

| category | values to try |
|---|---|
| parser | no args, `--help`, `--version`, unknown flag, missing value, duplicate flag, last-wins toggles |
| numbers | `0`, `-1`, `+1`, `1.5`, `nope`, huge, whitespace |
| ids | empty, whitespace, `.`, `..`, `a/b`, `a\\b`, absolute, `a:b`, `a?b`, `a*b`, control char, newline, surrogate, zero-width/bidi/line-separator, 129 chars |
| paths | empty, relative, missing, file, directory, symlink, broken symlink, FIFO, device, parent missing, parent is a file, path inside the run directory |
| revisions | empty, missing, `HEAD~999`, `HEAD^{tree}`, newline, NUL (if the OS permits) |
| configuration | absent, valid, malformed TOML/JSON, directory, non-UTF-8, broken symlink, FIFO, unknown key, wrong type, boolean where an integer is expected |
| prompts/instruments | missing, directory, FIFO, non-UTF-8, missing required placeholder, unreadable, non-executable |
| repository | missing, file, bare, `.git`, subdirectory, symlink |
| subprocess | binary missing, directory, non-executable, empty, NUL, missing `cwd`, timeout, non-UTF-8 stdout/stderr, empty final stream event |
| combinations | `--plan` with output flags, `--report` with `--json`, `--ephemeral`/`--no-ephemeral`, `--sandbox`/`--no-sandbox` |

Expected: every invalid case exits with the tool's **start-failure** code, prints a
single `tool: message`, and creates no run directory. `--help`/`--version` exit 0.
A diagnostic command may exit 1 for a failed check by design; state that
exception in the matrix.

## 4. Classify and fix

| symptom | fix |
|---|---|
| traceback | wrap the parser exception at the boundary; name the path/field |
| start failure reported as incomplete/negative | introduce a non-retryable start error; do not let a retry loop swallow it |
| exit 2 for a usage error | override the argument parser's error exit to the domain's start-failure code |
| temp tree left behind | preflight output paths; put cleanup on the error path as well as success |
| silent ignore | refuse the conflicting flag combination instead of accepting and ignoring |
| blocking on FIFO/device | require a regular file before opening; `lstat` before `is_file` |
| write outside the root | validate the segment, reject absolute second components, then assert the joined path is under the root |
| terminal controls | strip Cc/Cf/Cs/Zl/Zp in the human printer only |
| two runs share one output directory | claim with `mkdir(exist_ok=False)` before evidence; remove an empty claim on start failure |
| export/keep merges into an existing target | `copytree` without `dirs_exist_ok`; refuse the target and keep the source |
| non-UTF-8 child output crashes | `errors="replace"` on plain and stream transports; schema failure is a failed sample |
| JSON Pointer `-1`/`01` resolves | array index grammar `0|[1-9][0-9]*`; invalid index is `UNRUNNABLE` |
| failed sample hidden on FAIL | append missing samples/units to the reason; agreement is null if any output is missing |

## 5. Pin it

- Add one regression per **class**, not one per string; parametrize the values.
- Assert the exit code, the message prefix, **and** the absence of the side effect
  (no run directory, no output file, no child process).
- Run the real entry point in the test, not only the helper.
- When a guard is refactored, its mutation-check pattern goes stale. Retarget the
  mutation to the new guard; do not delete the mutation. A mutation that reports
  `pattern not found` is not a passing mutation.

## Pitfalls

- `argparse` exits 2 by default; 2 often already means "incomplete". Override
  `ArgumentParser.error` to the tool's start-failure code.
- `Path("")` is `.`; an empty string silently means the current directory. Use a
  custom `type=` that rejects an empty string when the flag is required.
- `root / "/tmp/x"` returns `/tmp/x`; validate before joining, and assert the
  resolved result is relative to the root.
- `exists()` follows a symlink and is false for a broken one; use `is_symlink()` or
  `lstat()` to see the link.
- `is_file()` is false for a FIFO, but opening it still blocks; check the file type
  before `open`/`write_text` **and before `read_text`**.
- `text=True` still decodes strictly. One invalid byte from a child raises
  `UnicodeDecodeError`; pass `errors="replace"` and let schema validation fail the
  sample.
- `copytree(..., dirs_exist_ok=True)` merges two evidence directories and can
  overwrite the earlier verdict. Refuse an existing target.
- An existence check followed by `mkdir(exist_ok=True)` is not a claim; two
  processes can both pass it. Use `mkdir(exist_ok=False)`.
- `int(part)` accepts `-1` and `01`; a JSON Pointer array index needs the
  `0|[1-9][0-9]*` grammar.
- A failed sample is not named by `if failed and verdict is PASS`; the FAIL branch
  must name it too, and agreement must be null if any sample has no output.
- An empty final stream event can override usable text events; fall back to the
  accumulated text when the final text is empty.
- `subprocess.run(cwd=missing)` raises `FileNotFoundError` exactly as a missing
  binary does; validate `cwd` separately or the message sends the user to reinstall
  a working tool.
- `TOMLDecodeError`, `UnicodeDecodeError` and a custom `ValueError` subclass are
  not caught by `except ConfigError`/`except ReviewError`; catch and re-raise at
  the boundary.
- A missing reviewer retried by a generic sample loop turns exit 3 into exit 2.
  Mark it non-retryable.
- A report/SARIF write that fails after the run must still remove the temp tree;
  preflight the destination so the failure happens before the expensive call.
- Sanitizing only stdout leaves stderr and `doctor` output open; sanitize every
  human printer, never the JSON payload.
