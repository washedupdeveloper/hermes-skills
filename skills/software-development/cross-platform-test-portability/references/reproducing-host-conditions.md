# Reproducing a host condition on a host you do not have

A platform-specific test failure is almost always reproducible on the machine you are
sitting at, because the failure depends on a *condition*, not on the OS. Find the
condition, build it, and the assertion fails for the same reason — which is what turns
"I think this is the macOS `/tmp` thing" into evidence.

State the claim before the probe, then show both sides. The output is the evidence, so
print the values rather than asserting silently.

## The condition behind a resolved-vs-raw path mismatch

macOS: `/tmp` → `/private/tmp`, `/var` → `/private/var`, and `TMPDIR` lives under
`/var`. So a value the code returned verbatim is a different *string* from the same
directory after `.resolve()`. Any symlinked directory reproduces it:

```bash
rm -rf /tmp/probe-real /tmp/probe-link
mkdir -p /tmp/probe-real && ln -s /tmp/probe-real /tmp/probe-link
python - <<'PY'
import importlib.util, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("mod", "scripts/<module>.py")
m = importlib.util.module_from_spec(spec); sys.modules["mod"] = m
spec.loader.exec_module(m)

link = "/tmp/probe-link"
os.environ["HERMES_HOME"] = link          # the env var the function reads
print("function returns      :", m.<fn>())
print("raw comparison holds  :", m.<fn>() == Path(link))
print("resolved comparison   :", m.<fn>() == Path(link).resolve())
PY
rm -rf /tmp/probe-real /tmp/probe-link
```

Expect `raw True`, `resolved False`. That is the macOS failure, reproduced, and it also
settles which side is wrong: the function returns the environment's value, so the
*test's* `.resolve()` is the defect.

## The condition behind an extensionless-fixture failure

Windows CreateProcess resolves an executable by extension, so a `#!/bin/sh` file with
no extension cannot run — the call fails and a `version()`-style helper returns `None`,
correctly, because the fixture is not executable there. You do not need Windows to see
that the test depends on execution; you need to check what the test requires.

Grep the test for the fixture it writes, then ask of each assertion: does this need the
file to *run*, or only to *exist*? The ones that need it to run are the POSIX-only ones.

```python
# The file has no extension, so Windows cannot start it. The tests below need that
# fixture to RUN, so they are POSIX-only.
_EXEC_FIXTURES_RUN = os.name != "nt"
```

## The condition behind a missing capability

Some code branches on a *facility* rather than an OS — `import pwd`, then return early
when the import fails — and where the facility is absent the correct behaviour **is**
that early return. A test asserting the capability worked is therefore wrong on the
platform that lacks it, and you cannot reproduce that by hiding the OS from the
interpreter.

Hide the module instead. Assigning `None` into `sys.modules` makes a later
`import <name>` raise `ImportError`, so the absent-dependency branch runs on any
platform:

```python
import sys
saved = sys.modules.get("pwd", _ABSENT)
sys.modules["pwd"] = None          # `import pwd` now raises ImportError
try:
    added = entry.ensure_passwd_entry(uid=4242, gid=4242, passwd=..., group=...)
finally:
    if saved is _ABSENT:
        sys.modules.pop("pwd", None)
    else:
        sys.modules["pwd"] = saved
assert added is False              # the fallback, pinned everywhere
```

Two payoffs: the branch that previously executed on one OS is now covered on all of
them, and the platform gap becomes an ordinary test rather than a skip.

Guard the *other* test — the one that needs the capability — on a capability probe
rather than the OS name, so it skips for the real reason:

```python
_HAS_PWD = importlib.util.find_spec("pwd") is not None

def test_a_passwd_entry_is_added_for_an_unknown_uid(tmp_path):
    if not _HAS_PWD:
        raise unittest.SkipTest("no pwd module: the passwd path is container-only")
```

`find_spec` reports what the interpreter can actually import, which is the question the
test is asking; `os.name` only correlates with it.

## Proving a platform guard actually fires

A guard is code, and untested code is a guess. Force the flag in a throwaway copy, run
it, and read the summary — `-rs` prints the skip reasons:

```console
$ sed 's/^_EXEC_FIXTURES_RUN = os.name != "nt"/_EXEC_FIXTURES_RUN = False/' \
    tests/test_x.py > tests/_probe_test_x.py
$ python -m pytest tests/_probe_test_x.py -q -rs
....s.....s......                        [100%]
SKIPPED [2] tests/_probe_test_x.py:69: a shebang fixture cannot execute on Windows
15 passed, 2 skipped
$ rm tests/_probe_test_x.py
```

The reason string appearing in the summary is the part that matters: it proves the skip
is deliberate and tells the reader why. Then run the real file on the host you have and
confirm the guard is a no-op there (same count as before).

## The condition behind a Windows checkout

A Windows GitHub runner has `core.autocrlf=true`, so the working tree it hands the tests
is CRLF before any code of yours runs. Reproduce that locally with one clone flag — no
Windows needed:

```bash
rm -rf /tmp/autocrlf-test
git -c core.autocrlf=true clone -q <repo> /tmp/autocrlf-test
```

Then count what the checkout actually contains, rather than assuming `.gitattributes`
did its job:

```python
from pathlib import Path
bad = [str(p) for p in Path("/tmp/autocrlf-test").rglob("*")
       if p.is_file() and ".git" not in p.parts
       and b"\r\n" in p.read_bytes()]
print(f"files with CRLF: {len(bad)}", bad[:10])
```

Zero means a tree-wide `* text=auto eol=lf` in `.gitattributes` is holding and the
CRLF-sensitive tests will pass there. Non-zero is the failure, reproduced. Run the
suite inside that clone too — it is the closest thing to the Windows job available on a
POSIX host.

## The condition behind "green locally, red on every runner"

CI pins an interpreter version; a devshell or venv usually has a different one. A
construct newer than the pinned version passes every local run and fails every job, so
read the version out of the workflow and test on it:

```console
$ grep -n 'python-version' .github/workflows/*.yml
  python-version: "3.12"
$ nix shell nixpkgs#python312Packages.pytest -c pytest tests/ -q
400 passed
```

For syntax alone you do not need the interpreter installed — `ast.parse` reports it:

```python
import ast
ast.parse(src, feature_version=(3, 12))   # SyntaxError on anything 3.12 cannot parse
```

Check any floor the documentation claims as a *separate* fact: "runs on Python ≥ 3.11"
and "CI tests 3.12" are two different assertions, and the lower one is the one users
will hit.

## Sweep the class, not the symptom

When a platform failure is unexplained, inventory the host assumptions before reading
files — the failing test is rarely the only one making the same assumption, and fixing
only it moves the failure to the next CI run:

```console
$ python scripts/platform-sweep.py <repo>
scanned 50 files under <repo>/{tests,scripts,bots,skills}
--- resolve-vs-raw  (62)
  tests/test_council_loop.py:1536  # Path(td).resolve() would be a different string...
--- temp-path  (25)
  tests/test_config.py:152  path = cfg_mod.config_path(hermes_home="/tmp/some-home")
```

Most hits are legitimate — the sweep is a list of questions, not findings. Then rule out
the filesystem-level cases by grep, which no content scan can do for you:

```bash
git ls-files | awk -F/ '{print tolower($0)}' | sort | uniq -d   # case collisions
git ls-files | grep -E '(^|/)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)|[ .]$'
```

An empty result for each is worth stating — it is what narrows the search to the one
test that does assume its host.
