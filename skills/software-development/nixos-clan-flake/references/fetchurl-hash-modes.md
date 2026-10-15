# fetchurl pins: flat vs recursive hashes

## The rule

`pkgs.fetchurl` hashes the fetched file according to `outputHashMode`:

| `outputHashMode` | What the hash covers | Compute it with |
|---|---|---|
| `"flat"` (default) | the file's bytes only | `nix hash file --type sha256 --base64 <file>` |
| `"recursive"` | the NAR serialisation: content **plus name and mode bits** | `nix hash path --type sha256 --base64 <file>` |

With `executable = true` and `outputHashMode = "recursive"` — what NixOS's
fetchurl module sets for a fetched script — the pin is the NAR hash of a **0755**
file. The flat hash of the same bytes is a different, unrelated value. Comparing
the two manufactures a phantom "hash mismatch".

## Test a pin correctly

```sh
# 1. does the pin survive a real, forced re-fetch? exit 0 == the pin is right
nix-store --realise --check /nix/store/<hash>-<name>.drv

# 2. read the mode the derivation expects
tr ',' '\n' < /nix/store/<hash>-<name>.drv | grep -E 'outputHash|outputHashMode|executable'

# 3. recompute the matching hash from the live content
curl -sSLo f "$URL"; chmod +x f
nix hash path --type sha256 --base64 f   # for recursive pins
nix hash file --type sha256 --base64 f   # for flat pins
```

A store path that is "not valid" while its *content* hashes correctly is a stale
or half-written path from an interrupted build — not evidence about the pin.

## Pitfall

Two different correct hashes for one file is the expected outcome, not a
contradiction. Anyone reporting `error: hash mismatch` from a flat-vs-recursive
comparison is wrong; answer with the table above instead of "fixing" the pin.
Replacing a recursive pin with the flat hash breaks the build.

Same family: `outputHash` alone does not tell you which function to use — always
read `outputHashMode` from the `.drv` before recomputing.
