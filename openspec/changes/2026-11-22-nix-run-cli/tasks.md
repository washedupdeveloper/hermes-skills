# Tasks

- [x] 1. Expose `packages.openspec` and `apps.openspec` from the flake, and put the CLI in the
  devShell.
- [x] 2. Replace every `npx` / `npm install -g` instruction with `nix run .#openspec --`.
- [x] 3. Replace the gate's version-literal parser with a form check, plus an `npx` ban that
  fires on invocations and not on prose.
- [x] 4. Assert `pkgs.openspec.version` equals `pins.openspecCli`, so a nixpkgs bump is a gate
  failure rather than a silent change.
- [x] 5. Re-point the e2e mutants at the new rule and the new command sites.
- [x] 6. Record the rule in `nix-flake-packaging`, the domain skill that owns it.
