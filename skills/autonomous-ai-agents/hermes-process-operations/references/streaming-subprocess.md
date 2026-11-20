# Reading a Hermes answer as a stream

Use this when a harness shells out to `hermes chat` and a silent child would
otherwise hold the caller for the whole sample timeout.

## What the stream looks like

`hermes chat --query-file FILE --oneshot -Q --format stream-json` writes one JSON
object per line:

```json
{"type":"system","subtype":"init","timestamp":123}
{"type":"text","text":"{\"sections\": ..."}
{"type":"result","exit_code":0,"text":"<the full final answer>","session_id":"..."}
```

The `text` events are chunks; the `result.text` is the complete final answer.
Prefer `result.text`; fall back to `"".join(text events)`. A non-zero
`result.exit_code` or a stream with no answer is a failure, not an empty answer.

There is no heartbeat during model thinking: a 7,954-byte review prompt showed a
62-second gap between `system` and the first `text` event. An idle watchdog must be
longer than that; 120 s is a working default.

## Reader outline

```python
import json, os, signal, subprocess, tempfile, threading, time

def _terminate(proc):
    if os.name == "posix":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    proc.kill()

def _read_stream(argv, timeout, idle_timeout):
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=errors,
                                text=True, bufsize=1,
                                start_new_session=os.name == "posix")
        deadline = time.monotonic() + timeout
        last = time.monotonic()
        stopped = []

        def watch():
            while proc.poll() is None:
                now = time.monotonic()
                if now - last >= idle_timeout:
                    stopped.append(f"stream went silent for {idle_timeout}s")
                    _terminate(proc)
                    return
                if now >= deadline:
                    stopped.append(f"did not answer within {timeout}s")
                    _terminate(proc)
                    return
                time.sleep(0.25)

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        text, final, exit_code = [], None, None
        try:
            for line in proc.stdout:
                last = time.monotonic()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "text":
                    text.append(str(event.get("text", "")))
                elif event.get("type") == "result":
                    final = event.get("text") if isinstance(event.get("text"), str) else None
                    code = event.get("exit_code")
                    exit_code = code if isinstance(code, int) else 0
            proc.wait(timeout=5)
        finally:
            watcher.join(timeout=1)
            if proc.poll() is None:
                _terminate(proc)
                proc.wait()
            if proc.stdout is not None:
                proc.stdout.close()
            errors.seek(0)
            detail = errors.read().strip()
        if stopped:
            raise OSError(f"{argv[0]} {stopped[0]}: {detail}")
        if exit_code not in (0, None) or proc.returncode not in (0, None):
            raise OSError(f"{argv[0]} exited {exit_code or proc.returncode}: {detail}")
        answer = final if final is not None else "".join(text)
        if not answer.strip():
            raise OSError(f"{argv[0]} stream ended without an answer: {detail}")
        return answer
```

## Why the process group matters

Killing only the direct child is not enough. A shell wrapper's `sleep` (or any
child) inherits stdout; after the wrapper dies the pipe is still open, the
`for line in proc.stdout` loop never sees EOF, and the watcher has already
exited. The live symptom is a guard that should fail in 2 s hanging until the
outer timeout. Always start the child in its own session and kill the group.

## Tests that catch the two real defects

1. **The child holds the pipe.** A fake reviewer:

```sh
#!/bin/sh
printf '%s\n' '{"type":"system","subtype":"init"}'
sleep 10
```

Run with `idle_timeout=1`; assert `OSError` matching `silent for 1s` and that the
test returns in about a second. Without the process-group kill this test hangs.

2. **The pipe is never closed.** A Python fake that prints a `result` event and
exits. Run under pytest with `filterwarnings = ["error"]`; an unclosed
`proc.stdout` surfaces as `PytestUnraisableExceptionWarning: Exception ignored
while finalizing file ...`. Close stdout in `finally`.

Use `#!{sys.executable}` for Python fake binaries: `/usr/bin/env` does not exist
inside a Nix build, and a `#!/usr/bin/env python3` fixture fails only in the gate.

## Plain-output stubs

`--format stream-json` changes the contract. A stub that prints the review JSON as
plain text must be run with `--no-stream`, or it will end with "stream ended
without an answer". Keep the switch on the caller, not in the stub: the real
reviewer and a plain test double are different transports.

## When the gateway rejects `--run-budget`

Some gateway-backed `hermes` builds reject `--run-budget` as an unsupported CLI
option and direct the setting to `agent.run_budget_seconds` in `config.yaml`.
Treat it as a capability of the installed build, not as a failure of the review
tool: enforce the deadline in the reader's watchdog and leave the Hermes budget
setting alone unless the caller owns that config.
