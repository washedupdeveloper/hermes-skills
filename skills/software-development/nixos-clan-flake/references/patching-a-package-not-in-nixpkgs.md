# Patching a package nixpkgs does not carry

Situation: an upstream package needs a plugin or an extra dependency added, and the
consumer repo's nixpkgs has no attribute for that package at all.

## Prefer the upstream override seam over wrapping

If upstream exposes `pkg.override { extraPythonPackages = [ x ]; }`, use it. Their
build then generates the wrapper's `PYTHONPATH` itself **and runs its own
plugin/core collision check** — visible in the log as
`=== Checking for plugin/core package collisions ===`. A `symlinkJoin` plus
`wrapProgram --suffix PYTHONPATH` postBuild produces a working binary while skipping
that check entirely: it is a patch around the packaging instead of through it.

Only the wrapper derivation rebuilds, because `extraPythonPackages` feeds the wrapper
and not the app's venv — the expensive half comes from the cache. Confirm by timing
the build rather than by reading the derivation.

## An overlay is a silent no-op when the attribute is absent

`overlays.default = final: prev: { x = prev.x.override { … }; };` does nothing and
reports nothing if `prev.x` is `null`, because the consumer's nixpkgs has no such
package. Seed it first, under the name the overlay expects:

```nix
let
  base = inputs.upstream.packages.${system}.minimal;
  seeded = pkgs.extend (_final: _prev: { x = base; });
in
(seeded.extend inputs.patch.overlays.default).x
```

## Build the extra package with the TARGET's nixpkgs, not the consumer's

Two flake inputs pin different nixpkgs revisions, so their interpreters differ
(measured: 3.14.6 upstream vs 3.14.7 in the consumer). `extraPythonPackages` is
resolved by `requiredPythonModules` **inside the target's build**, against the
target's interpreter. Building the plugin with the consumer's python puts a second
interpreter's site-packages on one `PYTHONPATH` — it works until something imports a
compiled extension.

```nix
let
  upstreamPkgs = import inputs.upstream.inputs.nixpkgs { inherit system; };
  plugin = upstreamPkgs.callPackage (inputs.patch.outPath + "/nix/plugin.nix") { };
in
inputs.upstream.packages.${system}.minimal.override {
  extraPythonPackages = [ plugin ];
}
```

## Deliberately omit `nixpkgs.follows` on the upstream input

Following rebuilds the app's whole dependency set against the consumer's nixpkgs — a
long build, and a version the app's own lock was never tested against. Without it the
input resolves to the derivation already in the store, so the patch costs a wrapper.
The trade-off is that the input then tracks its own pin, so bump it explicitly.

## Verify with the artifact, not the build log

- `readlink -f "$(command -v <bin>)"` → the new store path.
- `<bin> --version` → still the upstream revision: same app, wrapped.
- The wrapper's `PYTHONPATH` names the extra package's site-packages built by the
  **target's** interpreter, not the consumer's.
- Discovery reports the plugin from `entrypoint` **with any hand-copied plugin
directory deleted** — that deletion is what proves the wrapper is the source rather
  than the copy.
- One real invocation of the plugin's tool.

## Install, and record the rollback

`nix profile remove <name>` then `nix profile install <flake>#<attr>`. Put the exact
previous install command in the commit body: rollback *is* that command, and a profile
removed without it is a rebuild from memory.
