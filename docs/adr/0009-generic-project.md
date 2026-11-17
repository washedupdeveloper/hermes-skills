# A generic library: the gate is Python, the host is a label

The repository started as the skill library for one agent, and its machinery assumed that agent
everywhere: the gate was `nix flake check` over hand-written eval assertions, the installer was a
`setup.sh` that wrote that agent's config, the runtime guard was a plugin for that agent's tool
pipeline, the build packaged two plugins into its flake, and a live check installed the agent to ask
it whether it could see the tree.

The skills themselves were never the problem. `SKILL.md` with frontmatter is a format several agents
already read, and everything the gate enforced about a skill — frontmatter, name, the index window,
encoding, references — is a property of the text, not of a host.

## What changed

| Was | Now | Why |
|---|---|---|
| `nix flake check` as the gate | `python3 scripts/validate.py`, standard library only | Any machine, any OS, no install step. The command a contributor runs is the command CI runs. |
| Rules written twice (Nix eval + Python) | One implementation, in `validate.py` | Two implementations of one rule is the drift this repository forbids elsewhere. `nix flake check` now *calls* the script. |
| `setup.sh` writing one agent's config | `install.sh <dir>`, POSIX `sh`, symlink or copy | Plug and play: the caller names the directory their agent scans. |
| `plugins/library-guard` | Deleted; its rules are in `validate.py` | It enforced two rules inside one host's tool pipeline. The same rules now fail the gate on every host, and nothing was loaded by either config here. |
| `plugins/harness-audit` | Deleted | A request-token meter for one host's model loop; it measured the maintainer's setup, not the library. |
| `soul/caveman-voice.md` | Deleted | A system-prompt fragment for one host. The voice it stated is already the `caveman` and `reply` skills' subject. |
| `scripts/verify-live.py` | Deleted | It asked one agent's binary whether it could load the tree. Replaced by a per-host row in the README; the gate proves the tree, and the host proves its own loader. |
| `flake.nix` building plugins and an overlay | `checks` and a `devShell` | The flake is now an optional wrapper: `nix flake check` runs the same script under a pinned interpreter, plus the maintainer checks. |

## What did not change

- **The rules.** Every assertion the Nix eval tier made about a skill — the required fields, the
  57-character window and its boundary, name-equals-directory, uniqueness, every key parsed, every
  directory holding a `SKILL.md`, the category set, no CRLF — is in `validate.py`, and the Python
  tests carry a negative control for each one. Porting a rule without its control would have been a
  rewrite that proved nothing.
- **The repository's own CI assertions.** Workflow pinning, runner labels, the OpenSpec CLI pin and
  the formatter stay in `nix/tests.nix` and `nix/checks.nix`. They are maintainer hygiene, not
  library rules, and a contributor without Nix simply does not run them.
- **The skills.** Not one line of a skill changed in this ADR's commit except the frontmatter
  `targets:` label below.

## Host scope as a label

Eleven skills are worth having only inside one agent: they describe its profile system, its process
seams, its server, its container. They now declare `targets: [hermes]` in frontmatter and appear in
one table in the README, and `validate.py` enforces both directions — a host-prefixed skill without
the label fails, and a table row without a label fails. The label is data, not a directory move: a
second host's skills would sit in the same categories and declare their own target.

## The cost

`nix flake check` no longer asserts the skill rules in its own language, so a Nix user's failure
message comes from Python rather than from the evaluator with both values quoted. That is the trade:
one implementation, portable, at the price of the eval tier's nicer diagnostics for those rules. The
maintainer-only assertions keep the eval-tier form, where the argument for it still holds.