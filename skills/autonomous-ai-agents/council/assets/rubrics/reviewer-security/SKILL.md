---
name: reviewer-security
description: "Review Nix and web diffs for secrets and exposure."
version: 1.2.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: review-council
metadata:
  hermes:
    tags: [review, rubric, security, secrets, nix, web, owasp]
    related_skills: [review-council-orchestrator]
---

# Security Review Rubric (Nix / NixOS / Clan · web applications)

Review **only the diff** at the pinned SHA. Never include a secret's value — cite
its location only.

## Scoring anchors (0–100)

| Score | Meaning |
|---|---|
| 95–100 | No security-relevant change, or strictly hardening. |
| 80–94 | Minor hygiene issues only (no exploitable path). |
| 60–79 | Real weakness needing privilege or unusual conditions to exploit. |
| 30–59 | Exploitable weakness introduced by the diff. |
| 1–29 | Direct exposure of a secret, or a trivially exploitable defect. |
| 0 | Committed plaintext secret, or a public unauthenticated admin surface. |

**Hard cap:** any committed secret, or any service newly exposed to the internet
without auth, caps this category at **≤ 30** regardless of everything else. State
the cap explicitly in your rationale.

## Checklist

**Secrets**
- [ ] Secret material reachable from the Nix store (world-readable) — an inline
      literal where a `sops`/`agenix`/clan-`vars` indirection belongs.
- [ ] `builtins.readFile` on a secret path (forces content into the store at eval).
- [ ] `sops`/`vars` files with wrong `owner`/`mode`.
- [ ] Secret in a `systemd` unit `Environment=` rather than `EnvironmentFile`/`LoadCredential`.
- [ ] A secret printed, logged, or passed on a command line (visible in store/`ps`).

**Privilege & hardening**
- [ ] `security.sudo.extraRules` granting broad `NOPASSWD`/`ALL`.
- [ ] `users.users.<n>.extraGroups` gaining `wheel`/`docker` without justification.
- [ ] `initialPassword` / `initialHashedPassword` weak or shared.
- [ ] `services.openssh.settings.PasswordAuthentication = true` or `PermitRootLogin = "yes"`.
- [ ] `nix.settings.trusted-users` widened; `sandbox = false`; `allow-import-from-derivation = true`.
- [ ] `security.sudo.wheelNeedsPassword = false` introduced.

**Exposure**
- [ ] `networking.firewall.allowedTCPPorts`/`UDPPorts` opened for an ungated service.
- [ ] A service bound to `0.0.0.0` / `::` where it was loopback before.
- [ ] A new public endpoint with no auth (reverse-proxy route, `services.*.openFirewall = true`).

**Supply chain & purity**
- [ ] `fetchTarball`/`fetchurl`/`fetchgit` without a `hash`/`sha256`.
- [ ] `--impure` or `builtins.currentSystem`/`getEnv` smuggling impurity.
- [ ] A flake input tracking a moving branch for a security-critical component.
- [ ] `nixpkgs.config.allowUnfree` widened for a security-relevant package.
- [ ] A dependency with a known advisory introduced or retained without a note.

## Anti-patterns and their fixes

| Anti-pattern | Why it is bad | Fix |
|---|---|---|
| `SIGNING_KEY = "…literal…"` | lands in the world-readable store | `sops.secrets` + `config.sops.secrets.x.path` |
| `builtins.readFile ./secret` | content enters the store at eval | pass the path, read at runtime |
| `openFirewall = true` on a new service | silent exposure | explicit port list + auth in front |
| `trusted-users = [ "@wheel" "*" ]` | any user can inject into the daemon | restrict to the admin user |

## Commands (ground truth — run these first)

Grep-class checks; each is a hard signal, not a heuristic:

```bash
grep -rn 'builtins\.readFile' modules/ machines/ | grep -iE 'secret|sops|age|key'  # secret → store
grep -rnE -A3 'age\.identityPaths|sops\.age\.(sshKeyPaths|keyFile)' | grep -F '../'  # path literal, must be str
grep -rn -- '--impure' .github/ Makefile justfile 2>/dev/null                  # impurity in CI
grep -rn 'fetchTarball' | grep -v 'sha256'                                     # hash-less fetch
grep -rn 'allowUnfree'                                                         # blanket unfree
grep -rn 'accept-flake-config'                                                 # config injection
grep -rn 'trusted-users'                                                       # root-equivalence

`grep` rather than `rg`: `gnugrep` ships in the toolchain's shell dependencies, ripgrep
does not.
```

Store/closure hygiene (needs a Linux host with Nix):

```bash
nix store verify --recursive --sigs-needed 1 <toplevel>   # unsigned path count
nix why-depends --all <pkg> <dep>                         # reachability of a sensitive path
nix flake archive --json .                                # all inputs locked
# Advisory CVEs for the PINNED nixpkgs — the cheap, routine answer:
#   https://tracker.security.nixos.org/
```

**`vulnix` — on demand only, never probed.** It ships so closure CVEs can be asked
when they are the question; it is absent from `scripts/probes.py` because running it
is the expensive half: it fetches NVD data over the network (minutes; the answer
moves with the date), is unmaintained, and matches name+version, so backported fixes
are invisible — whitelisting is mandatory and this repo ships none. When wanted:

```bash
vulnix --system -w <whitelist.toml> --json
```

`--system` scans the closure of the machine RUNNING it, not the repository under
review. See docs/NIX.md.

**Multiplicative gates (not averaged):**
- any `builtins.readFile`-on-secret hit → **security category = 0**
- unsigned store paths found → security × 0.5

## Web applications — on demand

This rubric is **core**, loaded on every review. Web-application controls are not —
most diffs are not web diffs, and paying for that checklist every sample is waste.

**If the diff touches a web project** — HTTP handlers, auth, sessions, uploads,
database access, external APIs, PII, or LLM features — load the `web-app-security`
skill and score against it **as well as** this one. Where both apply, the score is
the **worst** applicable result.

If `web-app-security` is not installed, do not skip the dimension: report the web
surface as **unverified** and name the missing skill. Silence is never a clean bill.

## Evidence

Every finding carries `file`, `line_range`, a verbatim `evidence` snippet from the
pinned SHA, a `rule_id` where a tool produced it, and a `falsifiable_check` (the
command or read that would prove or refute it).

## Output

Findings as JSON per the review.msg/v1 findings schema, plus `score` 0–100 and a
one-line rationale naming any cap applied.

Write tersely: one sentence per `claim`, no hedging, no restating the diff. The
`caveman-review` skill is the format; the full contract is in the review prompt.
