---
name: hermes-terminal-backend
description: "Use when the agent's file or terminal tools fail."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: autonomous-ai-agents
metadata:
  hermes:
    tags: [hermes, sandbox, docker, podman, backend, troubleshooting, mounts]
    related_skills: [hermes-agent, nix-declarative-config, hermes-profile-fleet]
---

# Hermes terminal backend (container sandbox)

The agent's own execution environment is `terminal.backend` in `config.yaml` — `local`, `docker`, `podman`, `ssh`, `modal`, `daytona`, `singularity`. When it is a container, every `terminal`, `read_file`, `search_files` and `execute_code` call runs *inside* that container, and the container's mounts decide which host paths exist for the agent.

## When to Use

- Every file/terminal tool fails with a runtime error.
- The agent cannot see a project directory the user has open.
- Files the user "pasted" arrive as paths that cannot be read.
- The user is changing `terminal.docker_volumes` or the container image and expects the agent to see the result.

The bundled `hermes-agent` skill holds the config reference for these keys. This skill holds the diagnosis workflow.

## Rule 1: reproduce by hand — the traceback hides the real error

A backend failure surfaces as a Python traceback whose exception carries **only the exit code** of the runtime process. The runtime's stderr is captured and discarded, so the message that explains the failure never reaches you.

Never diagnose from the traceback alone. Extract the full runtime command — it is a Python list literal in the traceback, so join it — and have the user run it verbatim in their own shell with `; echo "exit=$?"` appended. That is what prints the real error.

## Rule 2: exit 125 means the container was never created

For podman and docker, 125 is a *create-time* failure, not a command failure. Check, in this order:

1. **Image absent from local storage.** Hermes pulls the image as part of the create call, under a **120-second** timeout (`# image pull may take a while`). A multi-GB image on a cold cache cannot finish in that window and surfaces as 125. The tell: a manual pull then succeeds and its output shows most blobs already present from the aborted attempt, after which Hermes works. A 125 that clears on its own after one manual pull is this, not a config fault.
2. **A bind-mount source that does not exist.** Every `-v host:container` needs a real `host` path.
3. **A stripped environment.** Rootless podman needs `HOME` and `XDG_RUNTIME_DIR`. Hermes builds a curated env for the subprocess, so a container that runs fine in the user's interactive shell can still fail under it.
4. **A different runtime binary.** The traceback names the runtime by absolute path; the user's runtime on `PATH` may be another build or version.

Fix a cold-cache recurrence durably: a `oneshot` unit that pre-pulls the image plus a timer to refresh it (`podman pull` is a no-op when layers are current). Also check whether an image auto-prune is enabled — a sandbox image is unused whenever the agent is idle, so a periodic prune recreates the cold pull on the next start.

## Rule 3: an empty directory mounted over a path makes the agent blind

A volume entry can mount a placeholder over a project path and hide it:

```
/var/empty:/workspace/projects/<repo>:ro
```

Signature of the masked path, read from inside the sandbox: **owner `nobody:nogroup`, epoch timestamp (`Jan 1 1970`), empty** — while sibling directories under the same parent look normal. A real project directory never has that shape.

Audit mounts from inside the sandbox instead of guessing:

```bash
grep -E 'hermes|projects' /proc/mounts     # what is actually mounted
stat -c '%n owner=%U:%G mode=%a' <path>    # nobody:nogroup + epoch = empty-dir mount
ls -la <parent>                            # siblings prove whether mounts work at all
```

Then find the generator on the host. The entry is usually declared in Nix and rendered into `config.yaml`, so grep both:

```bash
grep -n '<masked path or /var/empty>' ~/.hermes/config.yaml
grep -rn '<same>' ~/projects/<infra-repo>
```

Remove the volume. Do not "fix" it by creating the placeholder directory — that leaves the project masked.

## Rule 4: mounts are fixed at container creation

A container keeps the mounts it was created with. Editing the config that declares volumes changes nothing until **both** the config is re-rendered *and* the container is recreated. Order:

1. edit the source of truth (the Nix module)
2. rebuild so `config.yaml` is regenerated
3. verify the rendered file (`grep` for the removed and added entries)
4. only then remove the container so the next one is built from the corrected config

Removing the container first is a no-op: it is recreated from the unchanged config with the same mounts. Removing it also kills any tool call in flight, so warn the user that the current session's shell will die.

Confirm the container really was recreated by its id/hostname changing — not by the absence of an error.

## What the sandbox can and cannot see

The default volume set mounts `~/.hermes/skills` (read-only), the `~/.hermes/cache/*` subdirectories, `images`, `attachments` and `composer-pastes`. Paths outside that set are simply absent — most often `~/.hermes/pastes`, so a file the user pasted arrives as a path that cannot be opened.

Do not assert that list from memory; read it from inside the sandbox: `grep -E 'hermes' /proc/mounts`. To make another host path visible, add it to `terminal.docker_volumes` and create the source directory — a missing source is itself a 125.

## Working with the user on this

- **Hand over commands in one batch and wait for the whole batch.** Conclusions drawn from a partial batch are wrong and cost a round trip; expect to be told to await the rest. Collect all results, then reason.
- **A hypothesis that fits the exit code is not evidence.** Test it against observations you already hold before proposing a config change. A theory that predicts a symptom you have already observed *not* happening is dead on arrival — run the one-command discriminator instead of agreeing with it.
- When a hypothesis is disproved, say so plainly and retract the fix built on it. Do not leave a wrong diagnosis standing because a config change was already suggested.
- Send the cheap discriminators first, then a full-fidelity repro of the exact failing command with stderr visible.
- Separate what real output showed from what is inference.

## Pitfalls

- Don't stop at the first cause that matches the exit code. 125 has several independent causes and they are distinguishable only by running the discriminators.
- Don't record "the runtime is broken" as a conclusion. It is nearly always image state, a mount source, or environment — all fixable config.
- A config key added to fix a hypothesis that was later disproved must be removed or explicitly marked inert, or it becomes permanent folklore.
- If the rendered `config.yaml` still shows the old value after a rebuild, the module is not regenerating it (hand-maintained, or merged with keys Nix does not own). Resolve that before concluding the edit failed.
- A runtime's short-name resolution is a separate concern from this failure mode. Verify a theory about it with one pull before writing config for it.

Ready-to-run probe batches, the full-fidelity repro and the mount audit loop: `references/diagnosis-commands.md`.
