# Experimental features: enabling them, and the constraints

All verified on nix 2.35.2 unless noted. Companion to the priority order in
SKILL.md: Clan.lol -> flake-parts -> Nix3.

## A flake cannot enable the feature for `flake.nix` itself, but can for imports

Getting this distinction wrong is easy and costly:

- `flake.nix` is parsed *before* `nixConfig` is read, so a `|>` written in
  `flake.nix` can never be self-enabled. Hard bootstrap limit.
- A `|>` in an **imported** module is evaluated *after* `nixConfig` applies, so
  `nixConfig.extra-experimental-features` does enable it, for any caller that
  accepts the flake config (`--accept-flake-config`, or
  `accept-flake-config = true`).

Verified both ways on a scratch flake with the pipe in an imported file:

```console
$ env -u NIX_CONFIG nix eval --accept-flake-config --json '.#x'
[3,4]                                    # the flake's own nixConfig enabled it

$ env -u NIX_CONFIG nix eval --json '.#x'
error: experimental Nix feature 'pipe-operators' is disabled
```

So do **not** write "a flake cannot enable the features its own evaluation
needs": it is false for imported modules, and it wrongly argues against setting
`nixConfig.extra-experimental-features`. The entry requirement is narrower than
"always needs `nix.conf`" -- it applies only to a caller that declines the flake
config, or to a `|>` placed in `flake.nix` itself. The devshell's `NIX_CONFIG`
covers the interactive case and `direnv`'s `use flake` puts you in it.

### Tooling that does not accept the flake config by default

A `|>` in a module the machine config imports makes the repo depend on the
ambient config for **any tool that evaluates without accepting the flake
config**. The clan CLI is the concrete case: its internal `nix eval` calls do
not pass `--accept-flake-config`, so with no ambient config it dies on the pipe

```text
$ clan vars list host --flake .
Reason: experimental Nix feature 'pipe-operators' is disabled
    at .../modules/hermes.nix:84:7
```

Fix it by passing the option through -- the CLI exposes `--option name value`:

```console
$ clan vars list host --flake . --option accept-flake-config true
```

On a machine it is already moot: `base-system` sets `accept-flake-config = true`
in `/etc/nix/nix.conf`, so the plain invocation works there. `clan machines list`
and `clan show` never evaluate the machine config and are unaffected either way.

When a user asks "does the switch work?", these are the discriminating checks --
all host-side, none visible from inside a sandbox:

```console
$ grep experimental-features /etc/nix/nix.conf     # must list pipe-operators
$ nix eval --expr '1 |> (x: x + 1)'                # must print 2
$ nixos-rebuild list-generations | tail -3
$ clan vars list host --flake .             # the deep-eval canary
```

There is no in-Nix guard either: `builtins.langVersion` is `6` whether or not
`pipe-operators` is on, and no builtin exposes the enabled-feature set. So an
assertion with a friendly message is not possible; the parse error is what the
reader gets.

## `flake.nix` and `nixConfig` must be literal attribute sets

```text
error: file '.../flake.nix' must be an attribute set          # top-level let ... in
error: expected a set but got a thunk at flake.nix:7:3       # let-bound nixConfig
```

Both verified, the second also against a minimal scratch flake. A shared binding
therefore cannot be hoisted to the flake root. A value needed in two places in
`flake.nix` must be written twice with each copy pointing at the other, and the
reasoning recorded in `docs/`.

## `|>` semantics

| Expression | Means |
| --- | --- |
| `a \|> f` | `f a` |
| `f <\| a` | `f a` |
| `x \|> f \|> g` | `g (f x)` (left-associative) |
| `f 1 \|> g` | `g (f 1)` -- application binds tighter |
| `3 \|> add 4` | `add 4 3` |

`1 |> f + 1` parses but fails at evaluation with `cannot coerce a function to a
string`: the right side must be a bare function or a parenthesised expression
that evaluates to one. It is an eval-time type error, not a parse error.

Where it earns its place: chains of whole-value transformation that otherwise
read inside-out. `builtins.listToAttrs (map f slugs)` becomes
`slugs |> map f |> builtins.listToAttrs`, which is the order you would say it.

Where it does not: anything whose argument order puts the data last.
`lib.genAttrs names f` takes the names first, so piping inverts it and reads
worse than the call. Pipes on every expression is the same mistake as a comment
on every line -- the user asked for modern but readable, explicitly not
Haskell-like.

Toolchain: `nixfmt` (rfc-style) parses and formats `|>` and `<|` correctly, and
`deadnix` and `statix` fully parse files containing them. No lint will stop you
from overusing them, so the restraint has to be yours.

## `nix.settings.experimental-features` merges by concatenation

clan-core sets, at normal priority (`nixosModules/clanCore/nix-settings.nix`):

```nix
nix.settings.experimental-features = [ "nix-command" "flakes" ];
```

A list option merges by concatenation, so a second normal-priority definition is
*appended*. Two traps:

- Repeating the two defaults yields
  `experimental-features = nix-command flakes nix-command flakes pipe-operators`.
  Harmless -- nix ignores the repeat -- but it reads as a bug.
- `lib.mkDefault` on your own definition makes it **lose** to clan's
  normal-priority one, silently dropping your feature. The machine comes up
  without `pipe-operators` and the repo's own Nix code stops evaluating on it.

Correct shape: contribute only the extra feature, at normal priority.

```nix
experimental-features = [ "pipe-operators" ];
```

which merges to `nix-command flakes pipe-operators`. Verify by reading the
generated file out of the derivation rather than trusting the merge:

```console
drv=$(nix eval --raw '.#nixosConfigurations.<host>.config.system.build.toplevel.drvPath')
etc=$(tr ',' '\n' < "$drv" | grep -oE '/nix/store/[a-z0-9]{32}-[a-z0-9.-]*etc\.drv' | head -1)
conf=$(tr ',' '\n' < "$etc" | grep -oE '/nix/store/[a-z0-9]{32}-[a-z0-9.-]*nix\.conf\.drv' | head -1)
tr ',' '\n' < "$conf" | grep -o 'experimental-features = [^\\]*'
```

## Deciding which features to enable

Probe what the binary actually recognises rather than recalling a list. **Grep
the warning, not the exit code:** nix prints
`warning: unknown experimental feature 'X'` and still **exits 0**, so an
`&& echo exists || echo no` probe reports every name -- including a bogus
control -- as existing. Verified: `totally-bogus-feature` passes that way.

```console
for feat in nix-command flakes pipe-operators ca-derivations recursive-nix \
            dynamic-derivations fetch-closure auto-allocate-uids cgroups \
            daemon-trust-override impure-derivations local-overlay-store \
            parse-toml-timestamps read-only-local-store verified-fetches \
            blake3-hashes git-hashing external-builders configurable-impure-env; do
  out=$(NIX_CONFIG="experimental-features = nix-command flakes $feat" nix eval --expr 1 2>&1)
  case "$out" in
    *"unknown experimental feature"*) echo "NOT A FEATURE: $feat" ;;
    *) echo "exists: $feat" ;;
  esac
done
```

Always run a bogus name through the probe first to confirm it discriminates.

nix 2.35.2 recognises **19** features (count them, do not trust a number in a
previous session's notes -- this figure was written as 18 once and was wrong).
The ones not enabled here are the content-addressing family
(`ca-derivations`, `dynamic-derivations`, `impure-derivations`,
`fetch-closure`), store-layout experiments (`local-overlay-store`,
`read-only-local-store`), build isolation needing daemon-side root
(`auto-allocate-uids`, `cgroups`), and the rest with no consumer in a
single-machine homelab. `repl-flake` is gone -- removed in 2.22, folded into
`flakes`.

`pipe-operators` is the only one worth adding to a project like this, and only
where it removes nesting.
