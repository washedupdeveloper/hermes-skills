# Rendering the topology diagram

nix-topology builds the diagram from the machine configs plus the global
`topology.nix`; it is a flake output, never something to draw by hand. The
per-machine half is derived — any machine importing the nix-topology NixOS module
joins on its own — so a node in the render that `topology.nix` does not mention
came from that machine's `topology.self`. Read `machines/<name>/configuration.nix`
before assuming the global file is incomplete.

## Build

```bash
cd ~/projects/<repo>
nix build .#topology.x86_64-linux.config.output \
  --out-link /tmp/<repo>-topology --print-out-paths
ls /tmp/<repo>-topology        # main.svg, network.svg
```

- `main.svg` is the whole picture (uplink → router → host → guest, with
  services); `network.svg` is the networks-only view. The network view can omit
  link edges the main view draws — check `main.svg` before reporting a missing
  connection.
- The flake re-exposes this output as `checks.<system>.topology`, so
  `nix flake check` builds it. A plain build is therefore the cheapest proof the
  topology still evaluates — no VM, seconds.
- Wiring, the `perSystem.topology.modules` split and the per-service `details`
  override are documented in the repo's own `docs/adr/`. Read that before
  changing wiring instead of reinventing it.

## Rasterise for display

The SVG embeds its font as a base64 data URL, so it is self-contained and around
750 KiB. For inline chat display rasterise it at 2×:

```bash
nix run nixpkgs#librsvg -- -z 2 -b white -o <out.png> /tmp/<repo>-topology/main.svg
```

- `-z 2` doubles the size; at 1× the interface and address labels are unreadable.
- `-b white` because the diagram is dark-on-pale and transparent corners read as
  broken in some viewers.
- Copy the result into the Windows scratch dir **from inside the distro**
  (`cp … /mnt/c/Users/<you>/AppData/Local/hermes/cache/scratch/<dir>/`) and embed
  it with `MEDIA:`. A Windows-side `cp` cannot see `/tmp` in the distro.
- Look at the render before presenting it (`vision_analyze`): tofu or missing text
  means the rasteriser lost the embedded font, not that the diagram is wrong.

## Reading it back

The labels are the config — interface names, MAC addresses and service details
all come from `topology.self` and the service definitions, so the diagram is a
cheap way to see what the config actually says. When an address you expect is
absent, check whether the config deliberately omits a volatile value (a DHCP
lease that moves) rather than recording one that expires; a guest showing its
host's LAN address is a mirrored-network guest, not a modelling error.
