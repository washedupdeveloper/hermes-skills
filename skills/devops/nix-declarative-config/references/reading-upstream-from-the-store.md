# Reading an upstream flake's own sources

Option names, defaults, deprecations and published guidance differ between the
upstream website and the revision sitting in `flake.lock`, and the pinned copy
is the one that decides. Read it rather than guessing or trusting a summary.

## Locate an input's source tree

```console
nix eval --raw --impure --expr '(builtins.getFlake "/path/to/repo").inputs.<input>.outPath'
# -> /nix/store/<hash>-source
```

Works for any input in the lock, including `flake = false` ones. The same
expression form reaches nested inputs: `...inputs.clan-core.inputs.nixpkgs`.

### When the input is not realised (no store copy)

A sandbox with Nix that has never built the flake has no
`/nix/store/<hash>-source` for the input. Read the same file from GitHub at the
**`rev` recorded in `flake.lock`** — that revision is what decides, and the
branch tip is not it:

```console
# whole tree, filter it in code
curl -sL "https://api.github.com/repos/<owner>/<repo>/git/trees/<rev>?recursive=1"
# one file, verbatim
curl -sfL "https://raw.githubusercontent.com/<owner>/<repo>/<rev>/<path>"
```

Use it to settle whether an option exists at all, and with which default,
*before* writing config that sets it. Instance: `nix/homeManagerModules.nix` in
`NousResearch/hermes-agent` declares `programs.hermes-agent.desktop.enable` —
no summary of the module's option list would have confirmed that, and guessing
it would have been a coin flip. Same rule as everywhere else here: the
declaration at the pinned rev, not the website and not an earlier session's
inventory.

## What to read in there

| Path | What it settles |
| --- | --- |
| `options/*.nix`, or whatever declares them | the exact option path, type and default, and whether the option exists at all |
| `flake-module.nix`, `flakeModules/` | what the flake module actually adds to `perSystem` / `flake`, and with which defaults |
| `README.md` | the project's own instruction to *you* -- e.g. what belongs in `.gitignore` |
| `docs/src/**/*.md` | published guidance, migration notes and recommendations, at the pinned version |
| `templates/` | the shape upstream recommends for a repo like this; the fastest way to spot what your tree is missing |
| `checks/`, or the body of an assertion | whether a guard actually guards what its name claims |

Prefer the **declaration** over any prose. A description can contradict the code
that consumes it, and the code wins. Verified instance: clan-core's `module.input`
declares `default = null` with the defaultText "null which means the module is
local", while its resolver sends `null` to clan-core; setting it to `null` on a
locally-defined service fails with `clan-core doesn't provide clan-module with
name '<x>'`. The existing comment in `clan.nix` was right and the upstream
defaultText was wrong.

## Check the guard before trusting it

Read the assertion body, not its name. clan's `minNixpkgsVersion` check is only
`lib.versionAtLeast nixpkgs.lib.version "25.11"`, so it cannot catch a swap to a
mismatched-but-newer nixpkgs -- it is not a safety net for that decision. A
check whose body is weaker than its name is a common shape; do not cite one as
protection you have not read.

## Follow published guidance over your own reasoning

Before proposing a deviation from an upstream's arrangement, check whether they
have written a recommendation about it. clan has, in
`docs/src/guides/nixpkgs-flake-input/index.md` inside the pinned tree:

> **Option 1: Follow clan-core (recommended)** ... Every `clan-core` update
> brings a matching `nixpkgs` update, so you stay on a combination that has been
> verified end-to-end. The trade-off is that new upstream packages only reach
> you when `clan-core` bumps its input.
>
> **Option 2: Track your own nixpkgs** ... This gives you faster access to
> upstream changes, at the cost of running a combination that Clan's CI does not
> cover. Use it if you need a package or fix that has not yet landed in the
> version `clan-core` follows.

So `nixpkgs.follows = "clan-core/nixpkgs"` is the recommended setting, and the
precondition for deviating is a concrete missing package -- not a preference for
a git-pinned nixpkgs. Quote the guidance and follow it rather than framing a
settled question as an open trade-off.

## clan-core pins nixpkgs as a channel

```nix
nixpkgs.url = "https://nixos.org/channels/nixpkgs-unstable/nixexprs.tar.xz";
```

Following it makes the top-level `nixpkgs` lock node `type = "tarball"` rather
than a GitHub rev. That is expected, not corruption. Consequences worth knowing
before "fixing" it:

- It is a *floating* channel pointer with no `rev` to pin, so `nix flake update`
  moves it independently of clan-core's own pinned revision. Override with
  `--override-input nixpkgs github:NixOS/nixpkgs/<rev>` when you need a fixed one.
- It is `nixpkgs-unstable`, not `nixos-unstable`. Deliberate: clan also targets
  darwin, and `nixos-unstable` is NixOS-only.
- Substitution is fine. The lock's `narHash` is what makes a tarball
  substitutable at all, and the channel is what Hydra publishes to
  `cache.nixos.org`.

## Reproduce a bug and prove a fix, against the pinned tree

Reading tells you a guard is wrong; only a run tells you the defect is real — and a report
you publish about someone else's code is a claim like any other.

**Reproduce at the module level, not through a whole system.** A `lib.nixosSystem` with the
upstream module plus the smallest config that triggers it evaluates in seconds, and you can
read the failing attribute directly:

```nix
# repro.nix — nix eval --impure --json --file repro.nix
let
  nixpkgs = builtins.getFlake "path:/nix/store/<nixpkgs>-source";
  upstream = builtins.getFlake "path:/nix/store/<upstream>-source";
  sys = nixpkgs.lib.nixosSystem {
    system = "x86_64-linux";
    modules = [ upstream.nixosModules.default ({ ... }: { /* the minimal trigger */ }) ];
  };
in
sys.config.<the attribute under test>
```

`path:` refs keep it offline and pinned to the store copies; `--impure` is what lets
`getFlake` take a path at all.

**Isolate the input that causes it.** Re-run with the one option set to a harmless explicit
value. If it then evaluates, the finding is about that option's *default* — say so, because
"the feature is broken" and "the default is mishandled" need different fixes.

**Prove the fix on a patched copy, never on the store path.** The store is read-only:

```console
cp -r /nix/store/<upstream>-source /tmp/upstream-fixed
chmod -R u+w /tmp/upstream-fixed          # store files are 0444
# patch the file, then point the repro's `path:` at /tmp/upstream-fixed
```

A suggested fix that has not been run is a hypothesis. The patched copy is what turns
"`or` does not fire on a `null` default" into the rendered `listen[0] = "[::]:1883"` — and
that output is the difference between a report a maintainer can act on and one they close.

**Search before writing, and let the user publish.** One request
(`api.github.com/search/issues?q=repo:<owner>/<repo>+<term>`) rules out a duplicate. Filing
is a publication to a third party: put the complete body and the `gh issue create` command
in the repo's work list and hand it over, rather than assuming approval.
