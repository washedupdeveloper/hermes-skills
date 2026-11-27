# Measuring a build on a machine that has never built it

A warm run answers "how long does a rebuild take", which is not the question when the
claim is "this fits the CI timeout" or "this works on a fresh laptop". Measure against an
empty store, and say what it cost in bytes as well as seconds.

## The empty store

```bash
nix flake check --store "local?root=/tmp/cold-store" --keep-going
```

`local?root=` puts the store at `/tmp/cold-store/nix/store`: substitutions land there,
builds happen there, and the host store is not consulted. `--keep-going` so one red check
does not hide the rest of the measurement. A second run against the same root resumes, so
delete it first (`chmod -R u+w` then `rm -rf`) when the number has to be a first run.

## Prove it was cold

An empty root can still be fast because blocks were shared, so check both:

```bash
stat -c 'host inode %i' /nix/store/<path>
stat -c 'cold inode %i' /tmp/cold-store/nix/store/<path>
grep -c 'copying path' /tmp/cold-store.log
grep -c 'copying path.*cache.nixos.org' /tmp/cold-store.log
```

Equal inodes mean hardlinks — a local copy, not a fetch. Different inodes plus a high
count of `from cache.nixos.org` is a genuine cold run.

## Split substitution from build

Wrap the command so every line carries seconds since start; a first line of `building '`
is the end of substitution, the last line is the total, and the count of `building '`
separates "fetched a big closure" from "compiled a lot".

```python
import subprocess, sys, time
start = time.time()
p = subprocess.Popen(sys.argv[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     text=True, bufsize=1)
for line in p.stdout:
    print(f"{time.time() - start:8.1f} {line}", end="", flush=True)
sys.exit(p.wait())
```

Confirm the expensive tier actually ran rather than being skipped: grep the log for the
check's own derivations (`vm-test-run-`, the e2e names). A gate that omits a tier is a
gate that passes over less (see the "absence is not cleanliness" failure mode in
`deterministic-quality-gates`).

## Clean up

Store paths inside the root are `0555`/`0444`, so a plain `rm -rf` produces hundreds of
`Permission denied` lines and leaves the tree behind. `chmod -R u+w /tmp/cold-store`
first, then remove. A 6 GB root left in `/tmp` is exactly the state an ephemeral run is
supposed to avoid.

## Report it so someone else can scale it

Give the bytes and the link speed beside the total: 200 s on a 190 MB/s link and 200 s on
20 Mbit are different claims about someone else's machine. At 100 Mbit a 6.4 GB closure is
~9 minutes of substitution alone. State the timeout being compared against, and read that
timeout from the workflow rather than assuming it — a correction delivered afterwards
("it is 120 minutes, not 60") is better than a number the user has already acted on.
