# Hermes Desktop under Nix (home-manager), including NixOS-WSL2

`programs.hermes-agent.desktop.enable` is the declarative install of the
Electron app: it adds `hermes-desktop` to `home.packages` and writes an XDG
launcher entry on Linux. The app is a passthru of the same agent package, and
the wrapper sets `HERMES_DESKTOP_HERMES` to the Nix-built `hermes` binary, so it
installs no second runtime and downloads nothing on first start.

Option surface: `programs.hermes-agent.{enable,package}` and
`programs.hermes-agent.desktop.{enable,package}`. `services.hermes-agent` stays
the authority for state and config — the desktop reads `hermesHome` and the
backend address from it, never the reverse.

## Environment the launcher carries itself

A desktop-menu launcher reads no shell profile, so `home.sessionVariables` does
not reach it. The module passes these as wrapper `extraEnv` instead:

| Variable | When |
| --- | --- |
| `HERMES_HOME` | always — `cfg.hermesHome` |
| `HERMES_MANAGED` | only when `services.hermes-agent.enable`; it makes the CLI refuse a config edit and name the rebuild command, so an app installed without the services must not claim it |
| `HERMES_DESKTOP_REMOTE_URL` | only when a backend exists |

A secret belongs in `extraRun`, never `extraEnv`: `makeWrapper --set` writes the
value into the Nix store, which every user can read. The token is read at start
time from its file (`tr -d '\r\n' < <file>`).

## Backend: the app either starts one or borrows one

- `backend.mode = "none"` (default) — the app runs its own `hermes serve` over
the same `HERMES_HOME`. Sessions, skills, memory and config are shared with the
CLI/TUI, but the backend lives and dies with the window.
- `backend.mode = "serve"` — the module starts a `hermes-backend` user unit and
  points the launcher at it. Needed for cron, heartbeats and the messaging
  gateway, which require a process that outlives the window.

Both halves are required: the module sets the remote URL only when
`cfg.enable && cfg.backend.mode != "none" && cfg.backend.sessionTokenFile != null`.
Set one without the other and the resolver throws
`HERMES_DESKTOP_REMOTE_URL is set but HERMES_DESKTOP_REMOTE_TOKEN is not`.

This is a standing decision, not a detail — ask which shape the user wants
rather than defaulting.

## WSL2 / WSLg

The app renders through WSLg and needs nothing extra in the Nix config:

- NixOS-WSL binds the WSLg X11 socket (`/mnt/wslg/.X11-unix/X0`) to
  `/tmp/.X11-unix/X0`, and the Hermes launcher selects the Wayland ozone
  platform itself — do not add `desktop.electron_flags` for this.
- GPU is opportunistic: the launcher sets `GALLIUM_DRIVER=d3d12` only when
  `/dev/dxg` exists and Mesa's `d3d12_dri.so` is present, and falls back to the
  software rasterizer otherwise. An explicit `GALLIUM_DRIVER` or
  `LIBGL_ALWAYS_SOFTWARE` in the environment is left untouched.
- Precondition, not a config: WSLg must be present (`/mnt/wslg`,
  `$WAYLAND_DISPLAY`). Without it there is no window, and no Nix change fixes
  that — give the user the check to run instead of asserting it will open.

### Getting the entry into the Windows Start menu

NixOS-WSL's `wsl.startMenuLaunchers = true` rsyncs, on every activation, into
`/usr/share/applications` and `/usr/share/icons` from each of:

- `/etc/profiles/per-user/<defaultUser>/share/{applications,icons}`
- `/home/<defaultUser>/.nix-profile/share/{applications,icons}`

Windows' Start menu reads those directories, so a home-manager-installed entry
surfaces there with no extra wiring. Only those two subdirectories are copied,
so anything outside `share/applications` and `share/icons` does not reach
Windows.

The entry is named for the app id, not the product:
`com.nousresearch.hermes.desktop` (`APP_ID = "com.nousresearch.hermes"` in
`hermes_cli/linux_desktop_entry.py`). GNOME links a window to a launcher by that
id; `hermes.desktop` is kept only as a hidden legacy alias.

## Verifying the claim before making it

1. Confirm the option exists at the **pinned** revision by reading the
   declaration in the input's source — see
   `references/reading-upstream-from-the-store.md` for both the store route and
   the GitHub-at-the-locked-`rev` route. Do not confirm it from the docs page.
2. Confirm both consumers are wired: the home-manager module is in the HM import
   list, and the machine carries NixOS-WSL with `startMenuLaunchers = true`.
3. Hand the display precondition to the user as a command to run (WSLg present),
   since the sandbox cannot observe their display.
