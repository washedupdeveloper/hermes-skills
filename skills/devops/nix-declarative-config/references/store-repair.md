# When the Nix store and its database disagree

Symptom: `error: path '/nix/store/<hash>-<name>' does not exist` for a path
`nix path-info` calls valid; `nix develop` or `nix build` fails on a dependency the
database lists as live; `nix-store --delete` refuses with `still alive` referrers that
themselves do not exist.

Diagnose before deleting anything:

1. `nix store verify --all` lists every registered path whose file is absent; add
   `--check-contents` to compare hashes too.
2. `nix-store --query --referrers /nix/store/<path>` gives the chain keeping a dead path
   alive. If the only referrer is the path itself, normal liveness can never clear and
   `nix-store --delete` will refuse.
3. `nix path-info <path>` separates a registered-but-missing path (database divergence)
   from an unregistered stray file.

Repair, stopping at the first step that clears it:

1. `nix store verify --all --repair` re-substitutes what the cache can supply. **It cannot
   restore a `.drv`**: derivations are not generally substitutable, so a missing one is
   reported `cannot repair path ... No such file or directory` and its registration is
   dropped. That is progress, not failure.
2. Delete the stale registration so the next evaluation recreates it:
   `nix-store --delete --ignore-liveness /nix/store/<hash>-<name>.drv`, then re-run the
   command that needs it. A path that is its own referrer can still refuse; record it
   rather than hand-deleting files.
3. Re-run `nix develop`, `nix build .#<output>` or `nix flake check`; a successful rebuild
   re-registers the output.
4. Last resort with the database already inconsistent: dump it first —
   `nix-store --dump-db > /tmp/nix-db-$(date +%s).dump` — so `nix-store --load-db` can
   restore the registration list if a rebuild makes things worse.

Rules:

- **Never `rm -rf` a store path by hand.** The file goes, the row stays, and every
  liveness query now lies.
- **`--repair` cannot invent a derivation.** Expect to rebuild from flake evaluation.
- **A venv or container built to keep working is a workaround, not a repair.** The store
  is still damaged and the next `nix develop` still fails; say so and repair it.
- **Verify with three strengths:** `nix store verify --all` silent (registered paths
  exist), `nix develop -c true`, and a real `nix flake check`. One green build does not
  prove store consistency.
