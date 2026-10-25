# Joining someone else's overlay network from a clan machine

A machine has to join a mesh run by a third party (a club, a co-op): the peer list lives in
THEIR repository, the keypair is yours, and the interface must be the minimum that connects.
The shape below is WireGuard-specific because that is the common case; the rules about data,
keypairs and impact statements are not.

## Their peer list is DATA, not a module

- Read their files from a pinned input rather than copying values:
  `import (input + "/peers.nix")` and
  `builtins.fromJSON (builtins.readFile (input + "/inventory.json"))`. Merge them the way
  their own flake merges them — read it (`lib.recursiveUpdate a b` means the right side wins
  for lists and scalars) — and do not guess the order; the wrong order silently drops the
  fields the other file contributes.
- **Do not call their `lib`/`flakeModules` output for a four-field mapping.** Evaluating a
  flake output evaluates that flake and pulls ITS nixpkgs input in, for what is a
  `mapAttrsToList`. Repeat the mapping in one small file, cite the upstream path it mirrors,
  and let the gate's evaluation catch a shape change.
- Board support on new hardware is the opposite case: that DOES go through
  `clan.specialArgs` as a module (`references/adding-machines-to-a-clan.md`). Data is read,
  modules are imported.
- The input is pinned by the lock, so **`nix flake update <input>` is the security-relevant
  act** — it is what changes who is on the other end. Say so where the doc explains the
  network, because nothing else in the repository changes those keys.

## The keypair is a generator; only the public half leaves

```nix
clan.core.vars.generators.<mesh> = {
  files.key.restartUnits = [ "wireguard-<if>.service" ];  # a rotation must reach the interface
  files.pubkey.secret = false;                            # the half that gets registered
  runtimeInputs = [ pkgs.wireguard-tools ];
  script = ''
    wg genkey > "$out"/key
    wg pubkey < "$out"/key > "$out"/pubkey
  '';
};
```

- Registration happens in THEIR repository, as a pull request against the peer list — a step
  only the user can do. Hand them the public half from
  `clan vars get <machine> <gen>/pubkey`; never the private one, and never a printed secret.
- `--regenerate` is a **rotation, not a repair**: it invalidates the registration upstream,
  so it is never the fix for a connectivity problem. Say that in the generator's comment.
- The private half is deployed to `/run/secrets` like every other var and never enters the
  store; the public half is a public var, which is what makes it quotable in a PR.

## The minimum interface opens nothing inbound

- `networking.wireguard.interfaces.<if>` with `privateKeyFile`, `mtu`, `inherit peers`, and
  `ips` that stay EMPTY until the registration merges — the emptiness is what makes the
  pre-merge state inert rather than broken, so the branch can land before the PR does.
- **No `listenPort` means no firewall change and no peer can initiate.** Being reachable at
  rest is three deliberate things together — a listen port, a firewall rule, and a
  `selfEndpoint` in their peer list — and the doc should say they travel together.
- Know which peers are reachable at all: only entries carrying a stable endpoint can be
  contacted without a prior session; everything else needs one side to initiate. Count them
  and report the number rather than repeating a README's claim about the network at large.

## Say what it does to the machine, before it lands

The deliverable includes an impact statement, and it is the same shape every time: interface
and unit name · MTU · peer count and how many have a stable endpoint · this machine's
addresses before and after registration · the routed prefixes (AllowedIPs only; the default
route untouched, i.e. a split tunnel) · what is newly reachable inbound (usually nothing) ·
what DNS does (usually nothing) · and the blast radius. The blast radius clause that earns
its place: **a peer you have established a session with can reach services bound to
`0.0.0.0`**, so name the broker or the SSH daemon on that machine and the two mitigations
(bind the service to the LAN interface, or stop the interface when unused).

## Topology

nix-topology derives an interface for every interface the machine has, so a tunnel shows up
with `network = null`. Declare it — `topology.self.interfaces.<if> = { virtual = true; type =
"wireguard"; }` — and make the network assertion filter nulls with a comment saying why: an
assertion reading `i ? network` fails on the tunnel, and widening it without a note reads as
a weakened test rather than a description of a tunnel.
