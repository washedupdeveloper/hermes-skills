# Diagnosis commands: Hermes container backend

Send these as **one batch** and wait for every result before reasoning. Partial results invite a wrong inference.

## Batch 1 — cheap discriminators

```bash
# Does the image resolve and fetch from the user's shell?
podman pull docker.io/nousresearch/hermes-sandbox:desktop

# Does a bare container start at all?
podman run --rm docker.io/nousresearch/hermes-sandbox:desktop echo ok; echo "exit=$?"

# Same binary, environment stripped — mimics the curated env Hermes passes.
env -i PATH=/run/current-system/sw/bin HOME="$HOME" \
  /run/current-system/sw/bin/podman run --rm \
  docker.io/nousresearch/hermes-sandbox:desktop echo ok; echo "exit=$?"

# Which binary is Hermes actually invoking, and is it the same one on PATH?
ls -l /run/current-system/sw/bin/podman
/run/current-system/sw/bin/podman --version
podman --version; command -v podman

# Anything squatting the container name?
podman ps -a --format '{{.Names}} {{.Status}}'
```

Interpretation: a short-name pull that succeeds disproves any theory about unqualified search registries. A bare `podman run` that succeeds while Hermes fails points at environment or mounts, not the runtime or image.

## Batch 2 — every mount source exists

Podman exits 125 when a bind-mount source is missing. Audit the full list from the traceback:

```bash
for d in <each -v source from the traceback> ; do
  [ -e "$d" ] && echo "OK      $d" || echo "MISSING $d"
done
```

## Batch 3 — full-fidelity repro

Join the command from the traceback into one line, append `; echo "exit=$?"`, and run it. This is the step that surfaces the stderr Hermes discarded. Trim nothing.

Then, if it succeeds interactively, re-run it under `env -i` with only `PATH` and `HOME` to test the environment hypothesis.

## Mount audit (from inside the sandbox)

```bash
grep -E 'hermes|projects' /proc/mounts
stat -c '%n owner=%U:%G mode=%a' <path>
ls -la <parent>
```

`nobody:nogroup` + `Jan 1 1970` + empty = an empty directory mounted over the real path.

## Recreating the container after a config change

```bash
podman ps -a --filter label=hermes-agent=1
podman rm -f $(podman ps -aq --filter label=hermes-agent=1)
```

Run this **after** the rebuild has re-rendered `config.yaml`, never before. Verify the render first:

```bash
grep -n '<removed entry>' ~/.hermes/config.yaml   # expect no output
grep -n '<added entry>'   ~/.hermes/config.yaml   # expect a match
```

## Pre-pull so the image is never cold

Hermes's create call pulls under a 120 s timeout, so a cold multi-GB pull fails as exit 125. Keep the image warm declaratively:

```nix
systemd.services.hermes-sandbox-image = {
  description = "Pre-pull the Hermes sandbox image";
  wantedBy = [ "multi-user.target" ];
  after = [ "network-online.target" ];
  wants = [ "network-online.target" ];
  serviceConfig = {
    Type = "oneshot";
    RemainAfterExit = true;
    ExecStart = "${pkgs.podman}/bin/podman pull docker.io/nousresearch/hermes-sandbox:desktop";
  };
};
```

Add a periodic timer to refresh it, and check for an image auto-prune that would delete it while the agent is idle.
