# Is the clan sops store wired the right way?

"The secrets are encrypted" and "the store is coherent" are different claims. The second
one is checkable **without decrypting anything** and is what breaks quietly: a secret
that de-registers, a recipient nobody holds, an escrow that restores nothing.

The sibling reference `clan-vars-generators.md` covers authoring and generating a var.
This one covers whether the store that results is actually wired correctly.

## Clan discovers secrets by DIRECTORY SHAPE, not by a config file

`nixosModules/clanCore/sops.nix` builds `sops.secrets` by walking
`<clan.core.settings.directory>/sops/secrets`. A secret is registered for this machine
only when a marker exists for **this machine**, in one of exactly two places
(`containsMachineOrGroups`):

```
sops/secrets/<name>/secret              the sops-encrypted blob
sops/secrets/<name>/machines/<m>        registered for machine <m>
sops/secrets/<name>/groups/<g>          registered for group <g>
```

`groups` itself is `readDir sops/groups` filtered by whether the group directory contains
`machines/<machine>` — so a group counts only if this machine is a member of it.
`clan.core.sops.defaultGroups` is **not** the discovery mechanism: it is the default used
when *encrypting*, so a group named there but absent from `sops/groups` discovers nothing.

**A `users/<u>` marker is not a registration marker.** It says who may *decrypt*, which is
an encryption concern; only `machines/<m>` or `groups/<g>` makes the secret deploy. A
secret with users but no machine marker encrypts correctly and never reaches the host.

`containsSymlink` accepts `readFileType` in `{ directory, symlink }`, so either a real
directory or a symlink registers — a plain **file** at that path does not, and the secret
then silently stops deploying. Check the type with `git ls-tree`, which reports the mode of
the entry itself:

```bash
git ls-tree HEAD sops/secrets/<name>/machines/<m>   # 120000 blob = symlink, 040000 tree = directory
git ls-tree HEAD sops/secrets/<name>/groups/<g>
```

**Not `git ls-files -s` on a directory path** — that lists the files *inside* it at
`100644`, so a directory marker looks like a plain file and a reader "fixes" a marker that
was already correct. `git ls-files -s <path>` is right only for the symlink case
(`120000`). And git does not track an empty directory at all, so a marker that is an empty
directory is absent from the commit entirely; resolve a symlink with `readlink -f` too,
because a dangling one reads as present to git and absent to the module, which is the
worst of both.

**A missing `.sops.yaml` is correct for clan, not an omission.** Clan does not use sops
creation rules; its own template ships none and recipients live in
`sops/{machines,users}/*/key.json`. Do not "fix" its absence — adding one introduces a
second, competing source of truth for who can read what. (sops-nix repos that *do* use
creation rules need it; this layout does not.)

`vars/per-machine/<machine>/<generator>/<file>/` carries the same `machines/` and
`users/` symlinks, and clan registers those as `sops.secrets` too. A var with no
`machines/<m>` marker is generated but never deployed to the machine.

## Recipients must agree with the keys that actually exist

Each encrypted file carries its recipients in **plaintext** metadata, so reading them
needs no key and no decryption. What that metadata *looks like* depends on the file's
format, and the two shapes need different tools:

| format | envelope | how the recipient reads |
|---|---|---|
| `binary` (what clan sets) | JSON: `{"data": "ENC[…]", "sops": {"age": […]}}` | `jq -r '.sops.age[]?.recipient'` |
| `json` | the same shape, still valid JSON | `jq` reads it directly |
| `yaml` | `sops:` with an `age:` list, no quotes | `jq` **fails** (parse error); read it with `yq` or `grep` |

So a check that hard-codes `jq` reports zero recipients on a YAML-format store and looks
like "no recipients" rather than "could not read it". Read every shape with `grep` — the
recipients are public keys, so printing them is safe:

```bash
# recipients from any sops envelope, JSON or YAML
grep -oE '(recipient: *|"recipient": *")age1[a-z0-9]+' <file> | sed 's/.*age1/age1/'

# the machine's key derives to its registered recipient
git ls-tree HEAD vars/per-machine/<m>/<gen>/<file>/machines/<m>  # 120000 blob, or 040000 tree
age-keygen -y /var/lib/sops-nix/key.txt                          # public key only
jq -r '.[0].publickey' sops/machines/<m>/key.json
```

**Do not reach for `sops -d --extract '["sops"]["age"]'`.** `--extract` addresses the
*decrypted data tree*, and sops strips the `sops` metadata block from its decrypted
output — so on a clan var the branch fails and only a fallback ever runs. It also needs a
key, which contradicts the whole point of a check that reads the envelope.

A recipient count that matches the marker set (N user-readable, M machine-deployed) is
the evidence that the layout and the crypto agree. If the machine's key does not derive
to `sops/machines/<m>/key.json`, the machine cannot decrypt its own vars — that is the
failure a `hashedPasswordFile` override exists to paper over.

## An escrowed key that decrypts to nothing is a false recovery path

A `sops/secrets/<name>/secret` whose decrypted key is **not a recipient of any file in
the repository** is worse than absent: it is the file someone reaches for after losing
`/var/lib/sops-nix/key.txt`, and installing it restores nothing.

**Enumerate the encrypted files by CONTENT, and match both envelope shapes.** A glob like
`git ls-files 'vars/*secret*' 'sops/*secret*'` collects only paths containing the word
`secret`, so it misses every `vars/per-machine/<m>/<gen>/<file>/` blob — the files clan
actually encrypts to machine and user recipients. A live escrow whose key appears in none
of the collected files then reads as dead, and the next step deletes the only recovery
path. Match on the envelope instead, in **both** its forms — a quoted `"sops"` key is the
JSON/binary shape, an unquoted `sops:` is YAML, and a pattern with only one of them
silently skips half the store:

```bash
# every tracked file carrying a sops envelope, either format
git grep -laE '^sops:|"sops"' -- vars sops

# the real recipient set, format-independent; recipients are public keys
git grep -laE '^sops:|"sops"' -- vars sops \
  | while read -r f; do
      grep -oE '(recipient: *|"recipient": *")age1[a-z0-9]+' "$f" | sed 's/.*age1/age1/'
    done | sort | uniq -c

# then: age-keygen -y on the decrypted escrow, and look for that key in the list
```

`-l` prints paths only, so no ciphertext reaches the transcript, and the recipient grep
emits public keys, which are not secrets.

If the escrow key is in none of them, the escrow is dead — but only after confirming the
enumeration covered the tree. Either delete it (smallest correct action: removes a false
recovery path, adds no new secret) or re-encrypt the live `/var/lib/sops-nix/key.txt` to
the user recipients so it actually restores. Do not leave it and call the store fine, and
do not delete it on the strength of a check that structurally cannot see the evidence.

## Two more wiring details that are usually wrong

- **`vars/**` and `sops/**` must be excluded from treefmt AND pre-commit.** Formatting an
  encrypted blob rewrites bytes and destroys it. Both exclusions, not one — treefmt
  formats and pre-commit fails the commit, and either alone leaves a path that corrupts.
- **`format = "binary"`** is what clan's module sets, matching the
  `{"data": "ENC[AES256_GCM,…"` file shape. A file written as `yaml` with that content
  is unreadable by sops.

A commit message that says vars were "re-keyed to the host-derived age key" is a claim,
not evidence: check `sops.age.sshKeyPaths` and whether the machine recipient equals the
age form of the SSH host key (`ssh-to-age -i <hostkey.pub>`). When they differ, the key
is a standalone keyfile and the message describes a state the tree no longer has.
