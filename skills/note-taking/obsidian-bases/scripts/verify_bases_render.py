#!/usr/bin/env python3
"""verify_bases_render.py - prove that Obsidian actually renders a vault's `.base` files.

Parsing a `.base` file as YAML proves almost nothing. A base can be valid YAML, carry the right
view types and `groupBy`, and still render `Cannot find function "round" on type Duration` in
every age column - which is the class of defect that ships when a view is checked by reading it
rather than by looking at it.

Obsidian is Electron, so it can be driven over the Chrome DevTools Protocol and the rendered DOM
read back. This script restarts Obsidian with a debug port, opens every `.base` in the vault, and
fails on any expression-error text in a rendered view. It then restarts Obsidian *without* the
port, so the debug endpoint does not outlive the check.

    python verify_bases_render.py <vault> [--port 9222] [--timeout 90] [--keep-open]

Exit 0 = every base rendered clean. Exit 1 = a base failed, or a formula errored, or Obsidian
could not be driven. Requires a websockets client (`pip install websockets`) and Obsidian
installed. Process control uses tasklist/taskkill on Windows and pgrep/pkill elsewhere.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

# Text Obsidian puts in a rendered view when an expression fails. Stable substrings only: the
# surrounding message is version-dependent, the prefix is not.
ERROR_MARKERS = (
    "Cannot find function",
    "Unable to convert",
    "Invalid operator",
    "No such function",
    "Evaluation error",
    "Syntax error",
)

# A large table's innerText is otherwise megabytes; only the head is ever needed for errors.
TEXT_LIMIT = 60000


def obsidian_exe() -> pathlib.Path | None:
    override = os.environ.get("OBSIDIAN_EXE")
    cands = [pathlib.Path(override)] if override else []
    la = os.environ.get("LOCALAPPDATA")
    if la:
        cands.append(pathlib.Path(la) / "Programs" / "Obsidian" / "Obsidian.exe")
    cands.append(pathlib.Path("/Applications/Obsidian.app/Contents/MacOS/Obsidian"))
    for c in cands:
        if c.exists():
            return c
    return None


def running_pids() -> list[str]:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Obsidian.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True).stdout
        return [ln.split(",")[0].strip('"') for ln in out.splitlines() if "Obsidian.exe" in ln]
    out = subprocess.run(["pgrep", "-f", "Obsidian"], capture_output=True, text=True).stdout
    return out.split()


def quit_obsidian(timeout: int = 40) -> bool:
    """Ask Obsidian to close so it flushes its config, then force it if it will not.

    Obsidian holds its vault registry and any open `.base` file in memory and rewrites them on
    exit, so force-killing first risks losing a pending save - and the save is what turns a
    freshly created base from 0 bytes into a real view.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/IM", "Obsidian.exe"], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "Obsidian"], capture_output=True)
    for _ in range(timeout):
        if not running_pids():
            return True
        time.sleep(1)
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/IM", "Obsidian.exe"], capture_output=True)
    else:
        subprocess.run(["pkill", "-9", "-f", "Obsidian"], capture_output=True)
    time.sleep(3)
    return not running_pids()


def launch(exe: pathlib.Path, port: int | None = None) -> None:
    args = [str(exe)] + ([f"--remote-debugging-port={port}"] if port else [])
    flags = 0
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: the app must outlive this script.
        flags = 0x00000008 | 0x00000200
    subprocess.Popen(args, creationflags=flags, close_fds=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=(os.name != "nt"))


def wait_for_cdp(port: int, timeout: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version",
                                        timeout=3):
                return True
        except Exception:
            time.sleep(2)
    return False


def page_targets(port: int) -> list[dict]:
    """Every renderer window. Obsidian opens one per vault, so the target vault is
    usually NOT the first one - picking [0] silently verifies the wrong vault."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
            targets = json.load(r)
    except Exception:
        return []
    return [t for t in targets if t.get("type") == "page"]


VAULT_PROBE = "(window.app && window.app.vault) ? window.app.vault.getName() : null"


def find_vault_target(port: int, vault_name: str) -> dict | None:
    """The window actually showing `vault_name`, or None.

    Returning None must be fatal to the caller. Obsidian restores whichever vault was last
    focused, so on a machine with two vaults a check that does not confirm the vault will
    happily report "0 failures" for the other one - a false pass, which is worse than no
    check at all.
    """
    for t in page_targets(port):
        try:
            raw = asyncio.run(evaluate(t["webSocketDebuggerUrl"], VAULT_PROBE))
            got = raw.get("result", {}).get("result", {}).get("value")
        except Exception:
            continue
        if got == vault_name:
            return t
    return None


JS = """
(async () => {
  const app = window.app;
  if (!app || !app.vault) return JSON.stringify({error: 'no app.vault in this window'});
  const out = {vault: app.vault.getName(), bases: []};
  const targets = app.vault.getFiles().filter(f => f.extension === 'base')
    .map(f => ({path: f.path, kind: 'base'}));
  // A note can carry an inline ```base block, and those views render too. They are the
  // harder case to check: a broken formula inside a note is invisible unless the note is
  // opened and read, so a vault whose views live inline in one dashboard note would
  // otherwise pass this check while rendering errors on every line.
  for (const f of app.vault.getMarkdownFiles()) {
    const c = await app.vault.cachedRead(f);
    // A FENCE, not a mention: prose saying "inline ```base blocks" is not a view, and
    // counting it would pad the report with notes that render nothing.
    const fences = c.split(String.fromCharCode(10))
      .filter(line => line.trim() === '```base').length;
    if (fences > 0) targets.push({path: f.path, kind: 'inline', declared: fences});
  }
  for (const t of targets) {
    const p = t.path;
    const rec = {path: p, kind: t.kind, declared: t.declared || 1};
    const f = app.vault.getAbstractFileByPath(p);
    const leaf = app.workspace.getLeaf('tab');
    try {
      await leaf.openFile(f);
      await new Promise(r => setTimeout(r, 2000));
      const el = leaf.view.containerEl;
      const types = new Set();
      let text = '';
      // A long note mounts its base blocks lazily as they scroll into view, so one read
      // at the top misses every view below the fold - exactly where an unchecked formula
      // would sit. Read at the top, the middle and the bottom, accumulating both the
      // view types and the text.
      const scroller = el.querySelector('.cm-scroller')
        || el.querySelector('.markdown-preview-view') || el;
      const span = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
      const stops = span > 0 ? [0, span / 2, span] : [0];
      for (const top of stops) {
        scroller.scrollTop = top;
        await new Promise(r => setTimeout(r, 1300));
        [...el.querySelectorAll('[data-view-type]')]
          .forEach(e => types.add(e.getAttribute('data-view-type')));
        text += ' ' + el.innerText;
      }
      rec.viewTypes = [...types];
      // Count from the toolbar text without a regex literal.
      const at = text.indexOf(' results');
      let n = null;
      if (at > 0) {
        let k = at;
        while (k > 0 && text[k - 1] >= '0' && text[k - 1] <= '9') k--;
        const digits = text.slice(k, at);
        if (digits) n = Number(digits);
      }
      rec.results = n;
      rec.text = text.slice(0, LIMIT);
    } catch (e) {
      rec.error = String(e).slice(0, 200);
    }
    out.bases.push(rec);
    try { leaf.detach(); } catch (e) {}
  }
  return JSON.stringify(out);
})()
""".replace("LIMIT", str(TEXT_LIMIT))


async def evaluate(ws_url: str, expression: str) -> dict:
    import websockets
    async with websockets.connect(ws_url, max_size=None) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        await ws.recv()
        await ws.send(json.dumps({
            "id": 2, "method": "Runtime.evaluate",
            "params": {"expression": expression, "awaitPromise": True,
                       "returnByValue": True}}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 2:
                return msg


def open_vault(name: str) -> None:
    """Ask Obsidian to open a vault by name, so a check can target it deliberately.

    Obsidian restores whichever vault was last focused, which on a multi-vault machine is
    usually the wrong one. Rather than depending on that, the URI opens the one we want.
    """
    uri = f"obsidian://open?vault={urllib.parse.quote(name)}"
    try:
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "start", "", uri], capture_output=True)
        elif sys.platform == "darwin":
            subprocess.run(["open", uri], capture_output=True)
        else:
            subprocess.run(["xdg-open", uri], capture_output=True)
    except Exception:
        pass


def wait_for_vault(port: int, name: str, timeout: int) -> dict | None:
    """The target vault's window, opening it by URI if it is not already up."""
    t = find_vault_target(port, name)
    if t is not None:
        return t
    print(f"  '{name}' is not open; asking Obsidian to open it")
    deadline = time.time() + timeout
    asked = False
    while time.time() < deadline:
        if not asked:
            open_vault(name)
            asked = True
        time.sleep(3)
        t = find_vault_target(port, name)
        if t is not None:
            return t
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("vault", help="vault root containing the .base files")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--timeout", type=int, default=90, help="seconds to wait for CDP")
    ap.add_argument("--keep-open", action="store_true",
                    help="leave Obsidian running on the debug port")
    a = ap.parse_args()

    vault = pathlib.Path(a.vault).expanduser()
    if not vault.is_dir():
        print(f"verify_bases_render: not a directory: {vault}", file=sys.stderr)
        return 1
    bases = sorted(vault.rglob("*.base"))
    notes = []
    inline_re = re.compile(r"^```base[ \t]*\r?$", re.M)
    for p in sorted(vault.rglob("*.md")):
        try:
            if inline_re.search(p.read_text(encoding="utf-8", errors="replace")):
                notes.append(p)
        except OSError:
            continue
    if not bases and not notes:
        print(f"verify_bases_render: no .base files and no inline ```base blocks under {vault}",
              file=sys.stderr)
        return 1
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("verify_bases_render: needs a websockets client "
              "(`pip install websockets`)", file=sys.stderr)
        return 1
    exe = obsidian_exe()
    if exe is None:
        print("verify_bases_render: Obsidian not found - set OBSIDIAN_EXE to its path",
              file=sys.stderr)
        return 1

    print(f"verify_bases_render: {len(bases)} .base file(s) and {len(notes)} note(s) with "
          f"inline base blocks under {vault}")
    print("  closing Obsidian (it must flush .base files before we drive it)")
    if not quit_obsidian():
        print("  could not confirm Obsidian exited; continuing", file=sys.stderr)

    launch(exe, a.port)
    if not wait_for_cdp(a.port, a.timeout):
        print(f"  CDP did not come up on port {a.port}", file=sys.stderr)
        return 1
    target = wait_for_vault(a.port, vault.name, a.timeout)
    if target is None:
        open_vaults = []
        for t in page_targets(a.port):
            try:
                raw = asyncio.run(evaluate(t["webSocketDebuggerUrl"], VAULT_PROBE))
                open_vaults.append(raw.get("result", {}).get("result", {}).get("value"))
            except Exception:
                open_vaults.append("<unreadable>")
        print(f"  could not open '{vault.name}' - window(s) present: {open_vaults}. "
              f"Refusing to report a pass for a vault that was not checked.", file=sys.stderr)
        if not a.keep_open:
            quit_obsidian()
            launch(exe)
        return 1

    raw = asyncio.run(evaluate(target["webSocketDebuggerUrl"], JS))
    val = raw.get("result", {}).get("result", {})
    if "value" not in val:
        print(f"  evaluation failed: {json.dumps(raw)[:300]}", file=sys.stderr)
        return 1
    data = json.loads(val["value"])
    if "error" in data:
        print(f"  {data['error']}", file=sys.stderr)
        return 1

    # The window was chosen by matching the vault name, so a mismatch here is impossible;
    # keep the report for the record.
    print(f"  driving vault: {data.get('vault')}")

    failures = 0
    print(f"\n  {'view source':44} {'kind':7} {'layout':20} {'rows':>5}  status")
    for rec in data["bases"]:
        rel = os.path.relpath(rec["path"], str(vault))
        if rec.get("error"):
            print(f"  {rel:44} {rec.get('kind',''):7} {'':20} {'':>5}  FAILED TO OPEN: {rec['error'][:50]}")
            failures += 1
            continue
        hits = [m for m in ERROR_MARKERS if m in rec.get("text", "")]
        layout = ",".join(rec.get("viewTypes") or []) or "-"
        status = "ok" if not hits else "FORMULA ERROR: " + ", ".join(hits)
        if hits:
            failures += 1
        declared = rec.get('declared') or 1
        rendered = len(rec.get('viewTypes') or [])
        note = '' if rendered >= declared else f"  ({declared - rendered} block(s) never mounted - NOT checked)"
        print(f"  {rel:44} {rec.get('kind',''):7} {layout:20} "
              f"{str(rec.get('results')):>5}  {status}{note}")

    if not a.keep_open:
        print("\n  restarting Obsidian without the debug port")
        quit_obsidian()
        launch(exe)

    print(f"\nverify_bases_render: {len(data['bases'])} base(s), {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
