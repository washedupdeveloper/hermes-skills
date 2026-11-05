# External system footprint audit

Deciding whether to adopt a third-party product — a skill pack, an agent framework, an
"operating layer" — over a system you already run. The decision is made from measurements
of the candidate's tree and its installed surface, not from its documentation.

Run the probes from a script file, not an inline `wsl … sh -lc '…'` string: the distro's
login shell re-parses the constructs inside `-c` (see `hermes-wsl-backend`). On NixOS
there is no system `python3`, so use `awk`, or `nix shell nixpkgs#python3 -c python3 …`.

## 1. Clone and size the tree

```sh
git clone --depth 1 <url> /tmp/cand && cd /tmp/cand
for d in src tests tools skills benchmarks; do
  [ -d "$d" ] || continue
  echo "$d files=$(find "$d" -name '*.py' | wc -l) lines=$(find "$d" -name '*.py' -print0 | xargs -0 cat | wc -l)"
done
find . -name '*.py' -not -path './.git/*' | wc -l
find . -name 'SKILL.md' | wc -l
du -sh src tests skills docs
```

Quote both figures when the docs advertise a number and the tree disagrees. The gap is
unknown scope — do not resolve it in the candidate's favour.

## 2. Price the always-on context

A skill pack's descriptions are injected into the prompt before any tool call, so the
aggregate frontmatter is the recurring cost of adoption:

```sh
awk '/^description:/ {sub(/^description:[ ]*/, ""); t += length($0); n++}
     END {printf "skills=%d chars=%d tokens~%d\n", n, t, t/4}' skills/*/SKILL.md
```

Caveat: this counts any `description:` line, frontmatter or prose. Cross-check the skill
count against `find skills -name SKILL.md | wc -l`, and read the longest hits to confirm
they are frontmatter. Measured example: 153 skills → 53,023 characters ≈ 13k tokens,
against a 50-skill in-house library at a fraction of that.

## 3. What the installer writes into the user's environment

```sh
grep -n 'skills_dir\|config\.yaml\|external_dirs\|managed' install.sh src/commands/setup.py | head -20
grep -rn 'reverse_managed\|managed_config_writes\|managed_skill' src/install/ | head -20
```

Three things to establish: does it write config for you, does it keep reversal state for
those writes, and does it copy skills into `$HERMES_HOME/skills` (managed copies that a
plugin then polices) or reference an existing tree. Managed copies plus a mounted repo
gives one namespace two owners.

## 4. Authority the extension takes

```sh
cat src/plugin_bundle/*/plugin.yaml | head -40
grep -n 'requires_hermes\|provides_tools\|provides_memory_provider\|provides_' src/plugin_bundle/*/plugin.yaml
hermes --version
```

Compare the declared host range to the version actually installed — a gate that is already
unmet turns the whole install into a compat project. Count the tools and hooks it
registers, and treat `provides_memory_provider` as a memory takeover, not a feature.

## 5. Score against your own baseline

Same metrics on both sides, one row per dimension, and a verdict column:

| Dimension | Candidate | In-house | Decides what |
|---|---|---|---|
| Python LOC / test files | | | maintainability, reviewability in one session |
| Skill or module count | | | prompt cost, routing ambiguity |
| Gate quality | | | whether its claims can fail |
| Doc discipline | | | only whether to trust its *claims* |
| Files written into the user's env | | | ownership conflict, silent-write failure modes |
| Host-version coupling | | | cost of every upgrade |
| Surfaces served | | | whether the value is reachable for this user at all |

A candidate that is an order of magnitude larger and aimed at surfaces the user does not
use is not an upgrade, however good its ideas are.

## 6. Report shape

1. Bottom line first: adopt / do not adopt, and the single measured fact driving it.
2. The measurement table, with real numbers on both sides.
3. Where it would genuinely improve the in-house system — ranked, each matched to a
   named gap and a destination file.
4. What adopting it would cost — each item tied to a mechanism found in its tree.
5. What to take instead: N patterns, each with destination repo, effort estimate and the
   gate that enforces it, then the first one to build.
