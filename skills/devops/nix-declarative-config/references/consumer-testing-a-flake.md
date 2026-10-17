# Testing a flake the way a consumer meets it

Every check in a flake's own repository builds from a **local path**, so it exercises the
working tree. Nobody's tests exercise the published artifact — and the published artifact
is the only thing a stranger ever gets. A tree can be green, tagged and released while
the thing people consume is broken or mis-named.

Test it from outside: a throwaway directory whose **only** input is the published URL.

## The consumer flake

```nix
{
  inputs.<name>.url = "github:owner/repo";   # not path:., not a store copy

  outputs = { self, nixpkgs, <name> }:
    let
      system = "x86_64-linux";
      p = <name>.packages.${system};
    in {
      packages.${system} = {
        default = p.<installable>;
        toolchain = p.<other>;
      };
      apps.${system}.default = <name>.apps.${system}.<app>;
    };
}
```

Then three steps, each answering a different question: `nix flake show` (does it resolve
and evaluate), `nix build .#default --print-out-paths --no-link` (does it build), and
running the binary from the printed store path (does it work).

**`--no-link` means there is no `./result`.** Running `./result/bin/<cli>` after a
`--no-link` build fails with `No such file or directory` and reads like a broken package.
Use the store path it printed, or drop the flag.

## Learn the output names from the tool, never from memory

An output's name is not derivable from its purpose. `packages.default` is whatever the
author aliased it to — in one flake the *toolchain*, not the product — and the app's name
need not match the package's (`apps.council` beside `packages.review-council`). Query:

```console
nix flake show --json | jq -r '.packages."<system>" | keys[]'
nix flake show --json | jq -r '.apps."<system>" | keys[]'
```

A guessed name fails with `does not provide attribute 'packages.<system>.default'` or
`error: not an app definition`, and both read like a broken flake rather than a wrong
guess — so the mistake survives the diagnosis and lands in the docs. When you write the
outputs table, state the trap explicitly if `packages.default` is not the product,
because every consumer will assume it is.

**`packages` and `apps` are keyed by system.** `packages.default = x;` at the top level is
malformed and makes `nix flake show` fail with `not an app definition`; it must be
`packages.${system}.default`. Writing two dynamic keys for the same system in one attrset
(`packages.${system}.a = …; packages.${system}.b = …;`) also fails, with `dynamic
attribute 'x' already defined` — build one attrset per system.

## Importing a home-manager module without home-manager

A module that passes its own tests can still fail in a consumer's configuration, because
the consumer supplies a different surrounding config. Evaluate it with `lib.evalModules`
and read the resulting options back:

```nix
evaluated = lib.evalModules {
  modules = [
    <flake>.homeManagerModules.default
    {
      options.assertions = lib.mkOption { type = lib.types.listOf lib.types.anything; default = [ ]; };
      options.home.homeDirectory = lib.mkOption { type = lib.types.str; default = "/home/consumer"; };
      options.home.file = lib.mkOption { type = lib.types.attrsOf lib.types.anything; default = { }; };
      options.home.packages = lib.mkOption { type = lib.types.listOf lib.types.package; default = [ ]; };
      config.programs.<tool>.enable = true;
    }
  ];
  specialArgs = { inherit pkgs; };
};
```

Every `home.*` option and `assertions` that the module touches must be declared, because a
bare `evalModules` has none of home-manager's options — and each missing one fails with
`The option 'X' does not exist` **one run at a time**, so iterating on the error message
costs a flake evaluation per option. Enumerate them from the module instead:

```console
grep -oE '(home|assertions)\.[a-zA-Z.]+' <module>.nix | sort -u
```

Declaring them is not a workaround for a defect: a real configuration supplies all of
them, and the module legitimately uses `assertions` to refuse a misconfiguration. Also
declare whatever sibling module the target expects to find (`services.<other>`), or
evaluation fails on the consumer's behalf rather than on the module's.

Assert the **readback**, not that it evaluated: the mode, the resolved artifact store
path, a derived home path, and
`builtins.length (filter (a: !a.assertion) evaluated.config.assertions)` = 0. An
evaluation that succeeds while an assertion is failing is a broken deployment that looks
like a pass.

## What this cannot prove

The consumer flake proves resolution, build and evaluation **on the system you ran it
on**. It does not prove the artifact runs on a platform you did not build for, and it does
not prove a registry or container hub accepts a push. Say which of those you checked.

## Give the consumer a starting point, then guard it

A consumer test proves the artifact works; it does not tell a stranger where to begin.
Ship `templates` so the first step is one command instead of reading an outputs table:

```nix
flake.templates = {
  default = { path = ./templates/flake-parts; description = "…"; };
  home-manager = { path = ./templates/home-manager; description = "…"; };
};
```

- **`nix flake init -t <url>` requires `templates.default`** (or a top-level
  `defaultTemplate`). With only named templates it fails with `does not provide attribute
  'templates.default' or 'defaultTemplate'`, which reads like a broken flake — so alias
  the one most people want to `default` rather than making them learn the names first.
- **A template names a URL, not your tree, so nothing in your own gate sees it rot** —
  and a rotted template fails in *someone else's* repository, on their first command,
  where you never see the report. Guard it with a check asserting three things: the input
  URL is the **published** repo and not a `path:` / `file:` / relative one; the module
  import is still present (without it the flake evaluates to nothing at all); and its
  `systems` list equals the flake's, **derived from `flake.nix`** rather than duplicated,
  so adding a system here and forgetting the template fails instead of shipping a
  consumer who cannot build.
- **Prove the generated file, not just the template directory.** Run
  `nix flake init -t <url>` into a scratch dir, then `nix flake check --no-build` and
  `nix flake show` there, and check the output you promise actually appears.
- **A guard over a template must assert its own extraction found something.** A check
  that greps a systems list and then diffs the two results passes when the pattern stops
  matching, because it is comparing two empty files. `test -s declared.txt` before the
  diff is what makes the check able to fail.
- **Right after a push, `nix flake init -t github:owner/repo` can resolve the previous
  revision** — the branch-to-commit mapping is cached. Verify with the explicit rev
  (`github:owner/repo/<sha>`), or a missing new template reads as your bug when the ref
  is merely stale.
- **Templates are flake outputs, so they are public surface.** Naming `templates.*` in
  the versioning document is what keeps a later rename or removal an honest major rather
  than a silent break.
