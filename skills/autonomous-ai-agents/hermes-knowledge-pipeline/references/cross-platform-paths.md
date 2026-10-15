# One path, four platforms

## Resolver precedence

`$HERMES_KB_ROOT` → `$WIKI_PATH` → `$OBSIDIAN_VAULT_PATH` → OS default. Relative paths are
rejected with a reason. Precedence matters because the two Hermes conventions (`WIKI_PATH` for
`llm-wiki`, `OBSIDIAN_VAULT_PATH` for `obsidian`) must resolve to the *same* directory; when
both are set independently they drift and the vault silently splits in two.

## Per-OS defaults

| Platform | Detection | Default root |
|---|---|---|
| windows | `os.name == "nt"` | `SHGetFolderPathW(CSIDL_PERSONAL)/AI-Knowledge` — the shell API, so OneDrive Known-Folder-Move is honoured; `%USERPROFILE%\Documents` is wrong on redirected setups |
| wsl2 | `/proc/version` contains `microsoft` | `/mnt/c/Users/<winuser>/Documents/AI-Knowledge` via `cmd.exe /c echo %USERNAME%` interop, falling back to `~/AI-Knowledge` when interop is off |
| linux | fallback | `~/Documents/AI-Knowledge` |
| macos | `sys.platform == "darwin"` | `~/Documents/AI-Knowledge` |

WSL2 deliberately points at the Windows-side copy so Windows, WSL2 and an Obsidian desktop
install read the same bytes. A vault on ext4 is invisible to the Windows-side Obsidian.

## Path form

Always emit **native forward slash** (`C:/Users/x/AI-Knowledge`). It is the only shape that all
three of MSYS bash, `cmd.exe`, and native Windows binaries accept:

- `/c/Users/x` — MSYS-only; native tools fail with "cannot change to".
- `C:\Users\x` — needs escaping in every shell layer; survives neither `shlex` nor YAML cleanly.

## Links between the two sides of the same machine

Windows (no admin required; verify with a read-through of a known file):

```bash
cmd /c mklink /J "C:/Users/<u>/AI-Knowledge" "C:/Users/<u>/Documents/AI-Knowledge"
```

WSL2:

```bash
ln -s /mnt/c/Users/<u>/Documents/AI-Knowledge ~/AI-Knowledge
```

Then each host sets its own `WIKI_PATH` to its own native-looking path; content is shared,
configuration stays per-machine.

## Pitfalls

- **Never route `cmd.exe` builtins through the MSYS bash tool.** MSYS rewrites single-letter
  switches: `cmd //c mklink /J A B` dies with `'ache' is not recognized as an internal or
  external command` — the `/J` was consumed as a path. Invoke `cmd` from Python
  (`subprocess.run(["cmd", "/c", "mklink", "/J", link, target])`), which passes argv with no
  shell in between. `MSYS_NO_PATHCONV=1` also works but is easy to forget.
- **`HERMES_HOME` persists across terminal calls in a session.** A stale value silently
  redirects later `hermes` commands at the wrong home. Unset it after probing another profile,
  and resolve it in scripts instead of hardcoding `~/.hermes` — Windows installs live under
  `%LOCALAPPDATA%\hermes` and profiles under `$HERMES_HOME/profiles/<name>/`.
- **`.gitattributes` in the vault root: `* text=auto eol=lf`.** Without it, a vault edited on
  Windows and read from WSL2 produces CRLF churn that shows up as whole-file diffs and as
  `sha256` drift on `raw/` sources.
- **Gitignore machine-local state:** `.obsidian/` (regenerable cache), `_meta/kb-index.json`
  (derived), `_meta/distill-cursor.json` (per-machine position). Syncing these makes two hosts
  fight over one file.
- **Obsidian `userIgnoreFilters`** in `.obsidian/app.json` hides matched paths from Search,
  Graph View, unlinked mentions, and deprioritises them in Quick Switcher and link autocomplete
  — one setting covers every surface the user notices. Exclude `raw/`, `_archive/`, `_meta/`;
  keep `inbox/` visible because it is the review surface.
- **Say which branches you ran.** A resolver with one tested platform is untested on the other
  three; label them so a later session does not treat platform-conditional code as proven.
