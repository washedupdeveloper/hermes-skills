# clan.core.vars generators

## Shape

```nix
clan.core.vars.generators.<name> = {
  files.<file>.deploy = false;         # retrievable with `clan vars get`, never deployed
  files.<file>.neededFor = "services"; # users | services | activation | partitioning | boot
  runtimeInputs = [ pkgs.coreutils pkgs.mkpasswd ];
  script = ''...write into "$out"/<file>...'';
};
```

Consume a generated file as a path:
`config.clan.core.vars.generators.<name>.files.<file>.path`

Before generation `.path` evaluates to `/no-such-path`. That is the normal
not-yet-generated state, not an error.

## Generate without rotating anything else

```bash
nix develop --command clan vars generate <machine> --generator <name>
```

- `--generator` scopes the run to one generator; omit it and every generator for
  that machine runs.
- Never add `--regenerate` unless you intend to rotate existing secrets — that is
  the flag that resets passwords and keys.
- **`clan vars generate` commits the generated files to git itself.** Expect an
  extra commit you did not make.
- Prove nothing else moved: hash every file under `vars/` before and after and
  diff the two lists. Only the new generator's files may appear.

```sh
find vars -type f -exec sha256sum {} \; | sort > /tmp/vars-before.txt
# ... generate ...
find vars -type f -exec sha256sum {} \; | sort > /tmp/vars-after.txt
diff /tmp/vars-before.txt /tmp/vars-after.txt
```

## Verify and hand off

- Re-evaluate the consumer and confirm the path now resolves under
  `/run/secrets/vars/...`.
- The generated secrets are sops-encrypted at rest and tracked by git; that is
  the intended state, not a leak.
- A rotated credential is not live until the machine rebuilds. Give the user the
  retrieval command and say plainly that the device needs the new value before
  the service restarts:

```bash
nix develop --command clan vars get <machine> <generator>/<file>
```

## Notes

- Match what the consuming NixOS module expects, exactly. Mosquitto's
  `hashedPasswordFile` wants the hash **alone** on one line with no `user:`
  prefix, whereas `passwordFile` takes plaintext and is hashed by
  `mosquitto_passwd -U`. Read the option's description before writing the script.
- NixOS modules hand these paths to services through systemd credentials, so a
  `/run/secrets/...` value is a valid, working option value.
- A vars tree with no matching `clan.core.vars.generators` entry is orphaned: no
  `clan vars generate` can reproduce it. Grep the generators before assuming a
  tree is live, and delete it when it is not.
