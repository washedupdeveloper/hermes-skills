# A local binary cache

Serving a machine's own store to itself (or a mesh) so a second store refills by
substitution instead of rebuilding. Read this with the section of the same name in
`SKILL.md`; that one carries the design rule, this one the mechanics and the traps.

## Who signs, and what that implies

A store path carries signatures: "key K asserts this NAR has this hash". A client accepts a
substituted path when any signature validates against a key in its
`trusted-public-keys`. Three consequences drive everything else:

- **A server that does not build cannot sign.** `nix-serve` serves the narinfo already in
the database, so a path that arrived unsigned from `cache.nixos.org` stays unsigned and a
client with `require-sigs = true` refuses it. Adding a signature needs
`nix store sign --key-file`, and the *server* then replays that signature.
- **Signing at build time covers only what this machine builds.**
  `nix.settings.secret-key-files` makes the daemon sign every path it realises. Substituted
  paths keep the upstream signatures they arrived with, which is fine — every consumer
  already trusts that key.
- **A server that generates narinfo can sign everything.** harmonia signs the narinfo it
  emits, so one key covers built and substituted paths alike and the client only has to
trust one key. Verified: a path with no signatures of its own (`nix path-info --sigs`
prints only `ultimate`) came back from the cache with a `Sig:` line naming our key.

## The NixOS module

```nix
services.harmonia.cache = {
  enable = true;
  settings.bind = "127.0.0.1:5000";   # loopback: nothing exposed, no firewall rule
  settings.priority = 30;             # below cache.nixos.org's 40 → this cache is tried first
  signKeyPaths = [ keyFileFromSopsOrVars ];
};

nix.settings.extra-substituters = [ "http://127.0.0.1:5000" ];
nix.settings.extra-trusted-public-keys = [ "<name>-1:<base64>" ];
```

- The service is **socket-activated**: `ss -lntp` shows the listener and
  `systemctl is-active harmonia.service` says `inactive` until the first request. Do not
  read that as a failure — `curl http://127.0.0.1:5000/nix-cache-info` brings it up and the
  next probe says `active`.
- The key reaches harmonia as a systemd credential, not a readable file in the unit's
  namespace; the module mounts it and points `SIGN_KEY_PATHS` at it. That means the file
  needs to be readable by root at activation, which a sops-rendered or clan-vars path is.
- Gate the whole block on the key existing (a sentinel-path check), so a rebuild before the
  key is generated leaves the cache off instead of failing evaluation.

## Verify it, in this order

```bash
# 1. the listener, and that it serves
curl -sS http://127.0.0.1:5000/nix-cache-info

# 2. a path the host BUILT carries a signature in its narinfo
P=$(nix build --no-link --print-out-paths .#checks.<system>.<name>)
curl -sS "http://127.0.0.1:5000/$(basename "$P" | cut -d- -f1).narinfo" | grep '^Sig'

# 3. substitution is accepted with the key and REFUSED without it
store=$(mktemp -d)
nix copy --from http://127.0.0.1:5000 --to "local?root=$store" \
  --option require-sigs true --option trusted-public-keys "<name>-1:<base64>" "$P"
```

Step 3 is the one that matters: with the right key it exits 0, with a wrong or empty
`trusted-public-keys` it exits non-zero naming the signature. A test that only ever
substitutes successfully has not shown that the key is load-bearing.

## Traps, each measured

- **narinfo is at `/<store-hash>.narinfo`, not `/<full-basename>.narinfo`.** The hash is the
  32-character prefix. Querying the full basename returns `File not found` and reads exactly
  like a cache that cannot serve signed paths — it cost a wrong conclusion here before the
  URL was corrected.
- **`nix-serve` 0.2 cannot serve a current Nix.** It fails `invalid hash part` in its PSGI
  handler on the 52-character compressed-NAR hash that modern clients request, and the
  client sees HTTP 500 on `/nar/<hash>.nar`. Nothing about the store or the signatures is
  wrong; the server is simply older than the protocol.
- **A signing key passed to the daemon as `-m`/env on the command line is not how it is
  configured.** `secret-key-files` is a `nix.conf` setting; `nix config show` is how you
  confirm the daemon actually holds it after a switch.
- **A cold store built with `--store local?root=…` is not the host store.** Its outputs never
  land where the cache can serve them, so the first cold run populates nothing and the second
  one still rebuilds. To measure the cache's payoff you must first build the same derivations
  on the host.
- **`rm -rf` on a store root fails and floods stdout.** Store files are `444`/`555`, so
  `rm -rf /tmp/store-root` emits one `Permission denied` per file — measured at 158 KB,
  enough to corrupt a timing capture and bury the result. `chmod -R u+w <root>` first, or run
  it as root, and silence it (`2>/dev/null`) when the same command also produces output you
  are measuring.

## Keys

```bash
nix-store --generate-binary-cache-key <name>-1 secret.sec public.pub   # public: "<name>-1:base64"
```

The **public** half is not a secret: it belongs in the module as a literal, because
`nix.settings.trusted-public-keys` is evaluated at build time and cannot read a file that is
only materialised at activation. The **secret** half belongs in the repo's secret store,
never in the module and never in a commit.
