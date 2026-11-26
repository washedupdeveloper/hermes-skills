---
name: wireguard-mesh-triage
description: Use when a WireGuard mesh peer can't be reached.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, windows]
category: devops
metadata:
  hermes:
    tags:
      - networking
      - wireguard
      - diagnostics
    related_skills:
      - hermes-wsl-backend
writes: [none]
side_effects: [none]
scope_answers: ["why a WireGuard peer cannot be reached"]
scope_triggers: [wireguard peer unreachable, mesh handshake fails]
scope_out: [configuring the host firewall declaratively (nix-declarative-config), auditing what a run left behind (ephemeral-cleanup)]
---

# WireGuard mesh triage

## When to Use

Load this when a host on a WireGuard mesh cannot be reached from a peer, when a
peer reports a timeout against a service you believe is running, or when you are
about to propose a routing or registration change to fix mesh reachability.

Establish what is broken before changing anything. Three things produce identical
"it times out" reports and have nothing to do with each other: the service, the
peer's tunnel state, and the far side's routing.

## 1. Service first

When the service itself is in question — is it listening on the address the peer dials, does the
generated config match reality, will the host accept the packet, which interface does the traffic
leave by — the full ladder is `references/service-reachability.md`. It ends where this skill
begins: a service that answers locally and a peer that still times out.

Confirm the listener binds every interface, not loopback:

```sh
ss -lntp | grep <port>        # want 0.0.0.0:<port> and [::]:<port>
```

Also check the firewall is actually running (`systemctl is-active firewall`) and
`sysctl net.ipv4.conf.<if>.rp_filter` (2 = loose, 0 = off; neither drops replies).
A listener on `0.0.0.0` behind an inactive firewall is not the fault.

## 2. Per-peer liveness

```sh
wg show <if> latest-handshakes
wg show <if> transfer
```

A peer with a configured endpoint and `0 B received` since the interface came up
has **never** handshook. The far side does not hold your key, is not listening, or
moved ports. No routing change fixes that — say so instead of digging further.
Compare against a peer on the same host that does handshake to prove the path and
your key are fine.

## 3. AllowedIPs: the trap that looks like a routing problem

`wg` picks the peer by **longest prefix match over AllowedIPs**, not by the kernel
routing table. AllowedIPs is also the inbound source filter. A peer entry with no
endpoint and no live session therefore **black-holes its prefix** — you cannot
fall back to a broader hub route that covers it.

Signature: `ping` fails in 0 ms with `sendmsg: Destination address required` or
`Destination Host Unreachable` **naming your own address**. That error is local.

Confirm by lifting one peer off the live interface and retrying:

```sh
sudo wg set <if> peer <KEY> remove
ping -c2 -W2 <addr>     # ~1000 ms wait => packets left; 0 ms => still local
sudo wg set <if> peer <KEY> allowed-ips <v6>/64,<v4>/32   # restore exactly
```

Always restore in the same script and print `wg show` afterwards to prove it.

Corollary: for a NAT'd peer without `selfEndpoint`, adding a `/32` for it gives
every other member a black hole, not a route. Check whether the far side can ever
initiate before proposing registration.

## 4. RST beats silence as evidence

```sh
nc -vz -w 3 <host> <port>
```

- `succeeded` — listening.
- `Connection refused` — an RST: the host is **reachable**, the port is closed. This
  proves bidirectional IP connectivity and is the strongest evidence available
  without logging in.
- `Connection timed out` — nothing returned; routing, firewall, or a dead peer.

Do **not** wrap `nc` in `timeout N`: the kill hides the failure mode and prints
nothing. Use `nc`'s own `-w`.

ICMP is a weak probe — often filtered, and unrelated to a TCP service. Never
accept "ping timed out" as a statement about a port.

Sweep to find who is actually alive, then classify each host by RST vs timeout:

```sh
seq 1 254 | xargs -P 64 -I{} sh -c 'ping -c1 -W1 10.0.0.{} >/dev/null 2>&1 && echo up: 10.0.0.{}'
```

An RST from a host in a *different* subnet is proof that the hub forwards across
subnets — which redirects the investigation to the far side.

## 5. Pinned source addresses

If the far end's AllowedIPs for your key is `<your>/32`, packets sourced from any
other address are dropped on arrival. Test without committing:

```sh
sudo ip addr add <other>/32 dev <if>
ping -c2 -I <other> <hub-address>
sudo ip addr del <other>/32 dev <if>
```

No reply while the original address answers means the peer cannot be renumbered
unilaterally; the far side must change at the same time.

## 6. Read the vendor data before proposing a fix

- Run the project's own allocator with its own flags on a scratch copy to see what
  address it would actually assign.
- Where the allocator strips and reallocates (`STRIP = {"ipv4","ipv6"}`), a
  hand-pinned peer address does not survive the next regeneration.
- Check whether provisioning lives in the repo at all. Per-peer interfaces
  generated out-of-band (`wg.<peer>.luninet`, one listen port per member) are not
  in `peers.nix`, and a registration PR against the public data can be the wrong
  fix entirely — verify against the controller's actual config first.

## Environment note (WSL)

`wg`, `ip` and `ss` are the guest's tools. On a Windows host, every command here runs inside the
WSL distro — `wsl.exe -d <distro> -- bash /mnt/c/.../script.sh`, never a native shell.

`wsl.exe -d <distro> -- bash -c '...'` loses shell variables (a fish login shell
eats them): `D=/path` then `ls $D` lists the home directory instead. Write probes
to a script file and run `wsl.exe -d <distro> -- bash /mnt/c/.../script.sh`, where
variables, loops and functions behave normally.
