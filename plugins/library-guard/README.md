# library-guard

The skill library's contract, enforced where the writes happen instead of in CI minutes later.

| Hook | What it does | Why that seam |
|---|---|---|
| `transform_tool_result` | After a `write_file`/`patch` to a `SKILL.md`, the file is read back and validated against `library/contract.json`; every violation returns appended to the same tool result, naming the field and the fix. | The model still has the edit in context. The alternative is a red gate in another process, after the turn is over. |
| `pre_tool_call` | A write into a skill listed in `$HERMES_HOME/skills/.bundled_manifest` is **blocked**, with the reason: `hermes update` rewrites that directory. | The failure it prevents is silent: the edit applies, looks right, and disappears on the next update. |

## One implementation, three callers

`check_skill_text` is a pure function. The plugin, `scripts/skill-contract.py` (the gate), and
`tests/unit/test_library_guard.py` all call it, so the tree gate and the runtime cannot disagree
about what a valid skill is. The values it reads — the index window, the required frontmatter, the
category set — live in `library/contract.json`, one file shared with `nix/tests.nix`.

## Fail-open, deliberately

Every hook wraps its body and returns `None` on any error. A guard that can break a tool call is
worse than a missing one, and `pre_tool_call` callbacks that time out are treated as blocks by the
host — so this one does no I/O beyond one small file read, and caches the bundled-name set.

## Install

```bash
# drop-in, no packaging step
cp -r plugins/library-guard "$HERMES_HOME/plugins/"
hermes config set plugins.enabled '["harness-audit", "library-guard"]'

# or the distribution, through the overlay in nix/overlay.nix
nix build .#library-guard
```

Restart Hermes after installing: plugin discovery happens once, at startup.

## What it deliberately does not do

- No network, no model call, no configuration writes.
- It does not block a bad `SKILL.md` — it reports it. Blocking the write would cost the model the
  draft it is still working on; the note is enough to fix it in the same turn.
- It does not validate the body. Prose claims are `scripts/claim-audit.py`'s job, and a linter with
  opinions about style is the thing this repository already refuses to ship.