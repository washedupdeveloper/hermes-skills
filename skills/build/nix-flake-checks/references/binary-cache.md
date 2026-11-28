# A binary cache for your own builds

A store server looks like an obvious speed-up and usually is not one. Decide with the
counts below before wiring anything up.

## When it pays

| situation | does a local cache help? |
|---|---|
| the store was garbage-collected | yes — refill from a nearby server instead of the internet |
| a second machine or a fresh install | yes, if the server is reachable |
| a warm developer store | no: nothing to fetch |
| **a new commit** | **no** — every check is a new derivation, so nothing is substitutable |

Measured on a cold store running a full gate: **328 s with a local cache against 310 s
without**, because the checks were new. The same cache refilled a store whose paths the
host already had in **23 s against 245 s**. The cache does not make work faster; it
avoids work that was already done somewhere else.

**Measure it with a path the host already has.** `nix flake check --store X` builds
*inside* X, so the host store never receives those outputs and a cold run has nothing to
serve — the run looks like a cache failure and is really a measurement artefact. Populate
the host first (a normal gate run), then measure a second empty store against it.

## Who signs what

A cache **never signs**. A signature belongs to the store path, and a server either
replays it or generates its own narinfo:

- **the builder** — `nix.settings.secret-key-files = [ key ]` signs every path the daemon
  builds, as it builds it;
- **the server** — harmonia's `signKeyPaths` signs the narinfo it serves, so one key covers
  everything it hosts, including paths substituted from upstream;
- **neither** — a server that only replays narinfo (nix-serve) leaves every unsigned path
  unsigned, and a client with `require-sigs = true` refuses it.

So a client trusts *the key that actually signed*. With a re-signing server that is one
key; with a replaying one it is your key for your builds **and** `cache.nixos.org`'s for
theirs.

## Prove it before declaring it done

Three probes in an **empty** store, and the third is the one that catches a fake:

```bash
nix copy --from http://127.0.0.1:5000 --to "local?root=$tmp" \
  --option require-sigs true --option trusted-public-keys "<key>" <path>
```

| probe | expected |
|---|---|
| correct public key | accepted |
| wrong key | refused |
| no key | refused |

Two traps that make the probe lie. Never pre-copy the path into the target store: the build
"succeeds" from the local copy and reports success for every key. And read narinfo at
`/<store-hash>.narinfo` — the 32-character hash alone, not the full basename; the wrong URL
returns 404, which reads as "this cache cannot serve that path" when it is only the URL.

To force a genuinely new output for a signing test, perturb the tree (a comment is enough)
so the derivation hash changes — Nix signs what it *builds*, so re-testing an existing path
proves nothing.

## Wiring harmonia

```nix
services.harmonia.cache = {
  enable = true;
  settings.bind = "127.0.0.1:5000";
  signKeyPaths = [ config.sops.secrets.binary-cache-key.path ];
};
```

- **`services.harmonia.cache.*`, not `services.harmonia.*`.** The un-nested option was
  renamed; using it emits a deprecation warning, and a repository whose integrity check
  fails on any evaluation warning goes red for a reason that names the option.
- The key arrives as a **systemd credential**, not a readable file in the unit's namespace.
- The service is **socket-activated**: the listener is up before the service is, so
  `systemctl is-active` reads `inactive` until something connects. Hit
  `/nix-cache-info` once before concluding it is broken.
- Store the secret in the project's own secret store and verify the round trip
  (`… get <name> | diff - <original>`), rather than leaving a plaintext key on disk.

**nix-serve 0.2 is not a drop-in.** It answers `invalid hash part` for the compressed-NAR
URL a current Nix client requests, and it has no signing option at all. Reach for harmonia
unless the pin carries a newer nix-serve.

## Binding

Default to loopback. Expose the listener as **one option** and derive the substituter URL
from it, so a site that later shares the cache changes a single string.

Never bind `0.0.0.0` on a host without a firewall — the WSL module disables it outright, so
"the firewall will stop it" is not a plan. A mesh address works when peers share the cache
and needs no TLS, because the tunnel already encrypts it.
