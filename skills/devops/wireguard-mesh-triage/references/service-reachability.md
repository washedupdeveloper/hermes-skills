# Is a service on the fleet actually reachable?

Work down this ladder in order — each step invalidates the ones after it, and the
step people skip is usually the last one.

## 1. What is listening, on which address

```bash
sudo ss -lntp          # -lntup for udp; root for the process column
```

`127.0.0.1:PORT` is unreachable from anywhere but the host, whatever routing
says. `0.0.0.0:PORT` and `[::]:PORT` are all interfaces, tunnels included.

## 2. What the generated config actually says

NixOS has no FHS, so `/etc/<svc>/<svc>.conf` often does not exist and treating
that as "no config" is a wrong conclusion. Take the real path from the unit:

```bash
systemctl show <unit> -p ExecStart      # → … -c /nix/store/…-<svc>.conf
systemctl cat <unit>                    # RestrictAddressFamilies, PrivateUsers, User
cat /nix/store/…-<svc>.conf
```

This settles auth without guessing: for mosquitto, `per_listener_settings true`
with a `listener` line means `allow_anonymous` is false, so an unauthenticated
connect is refused rather than accepted.

## 3. Will the host accept the packet

```bash
systemctl is-active firewall
sysctl net.ipv4.conf.all.rp_filter net.ipv4.conf.<if>.rp_filter
```

On WSL, `nixos-wsl` sets `firewall.enable = false`, so every
`networking.firewall` rule in the flake is decorative there — "the rule exists"
is not evidence that anything is filtered. `rp_filter = 2` (loose) passes an
asymmetric path; `1` (strict) can drop a mesh return path that looks fine
outbound.

## 4. Which interface the traffic actually takes

```bash
ip route get <dest>           # on the target, for the reply direction too
ip -br addr; ip route; ip rule
```

A probe only means something once you know the interface it rode: one address can
resolve to the LAN NIC, a tunnel, or a stale route. On this setup `ip rule`
matters too, because the WSL mirror's rules are load-bearing (`hermes-wsl-backend`).

## 5. If the path is a tunnel: is the peer established

```bash
sudo wg show <if>
sudo wg show <if> latest-handshakes   # epoch seconds per peer; 0 = never
sudo wg show <if> transfer            # rx / tx per peer
```

The failure modes name different faults — read them apart:

| Reading | Means |
| --- | --- |
| `Destination Host Unreachable from <your own tunnel addr>`, `ping: sendmsg: Destination address required` | Your kernel could not send: no endpoint or session for that peer. Local failure, not a remote refusal. |
| A peer with **no `endpoint:` line** | Cannot be initiated toward; reachable only after it initiates. Silence proves nothing about that host. |
| `latest handshake: never` + `0 B received` + a climbing **sent** counter, on a peer that *does* have an endpoint | The far side is not answering at all — wrong key, moved port, nothing listening. Nothing above this layer can be healthy until it moves, so measure it before theorising about forwarding or registration. |
| `100% packet loss` with no errors, after the full timeout | Packets left and nothing returned — far-side routing or filtering. |
| Recent `latest handshake`, moving transfer counters | That leg is healthy; look further along the path. |

Read `latest-handshakes` and `transfer` rather than the formatted lines: `0` is
unambiguous where "never" is easy to miss in a long `wg show`, and **sent climbing
while received stays 0** across repeated probes separates "the UDP arrived and was not
decrypted" from "the packet never left".

### AllowedIPs is a longest-prefix table, so a dead /32 outranks a working /18

WireGuard selects the peer by longest matching prefix. One entry holding
`<member>/32` black-holes that host even while a healthy relay peer holds a covering
`/18`: the specific route wins, and a peer with no endpoint then fails locally with the
0 ms error above. A relay cannot rescue any address that also exists as a per-peer
`/32`, which is why "route it through the hub" answers nothing until the shadowing
entry is dealt with.

Prove it on the live interface, then restore:

```bash
sudo wg show <if> | grep -A3 <shadowing-peer-key>   # snapshot allowed-ips FIRST
sudo wg set <if> peer <shadowing-peer-key> remove
ping -c 2 -W 3 <member>                            # now takes the relay
sudo wg set <if> peer <shadowing-peer-key> allowed-ips <v6/64>,<v4/32>   # verbatim
sudo wg show <if> | grep -A3 <shadowing-peer-key>   # the restore is a claim: show it
```

The restore must reproduce the `allowed ips:` line byte for byte, endpoint and
keepalive included. A full timeout with no local error means the packet left via the
relay and nothing came back — a far-side fact, not a local one.

### AllowedIPs is also the inbound source filter

The same list decides which *source* addresses a peer's packets may carry, so adding a
NAT'd peer with no endpoint to the peer data does not create a route to it: it creates
a black hole for us **and** a source filter for them. Before proposing "register the
peer" as the fix, say which of those two it solves.

### A peer's address is pinned by the far side — test before renumbering

Adding an address locally does not make the tunnel accept it; the far end's AllowedIPs
for your key is the filter. Test the candidate before touching config:

```bash
sudo ip addr add <candidate>/32 dev <if>
ping -c 2 -W 2 -I <candidate> <your-gateway>   # answers = that source is accepted
sudo ip addr del <candidate>/32 dev <if>
```

No answer from a gateway that answers your registered address proves the address is
fixed by whoever configured the far side, so "move it into the members' subnet" is not
a change this machine can make.

## 6. Is the address part of the network at all

The step that gets skipped. On a config-managed mesh, AllowedIPs **is** the
routing table and it is generated from peer data. An address absent from that
data is in no member's tunnel, and no listener, firewall or rebuild change fixes
it.

```bash
ls -d /nix/store/*source*/peers.nix
grep -n '<peer>' /nix/store/<hash>-source/peers.nix
grep -o '172\.29\.[0-9]*\.[0-9]*' /nix/store/<hash>-source/inventory.json | sort -u
```

Then check the same file on upstream's default branch (fetch it raw). The pair
answers different questions: absent from both means a registration PR is needed;
present upstream but not in the lock means `nix flake update <input>`.

Compare **subnets**, not just addresses: members in `172.29.80.0/24` and a peer
holding `172.29.83.15/32` are different ranges, and a gateway answering in one
proves nothing about forwarding between them. AllowedIPs entries are per-member,
so even a registered peer needs every other member to carry a route back to it.

**Run the project's own allocator before hand-writing an address.** Where the mesh
ships one it is the authority on what a valid entry looks like, and it exposes
constraints the prose does not. Take the real flags from the flake's app, not memory:

```bash
grep -n -A15 'update-inventory' /nix/store/<hash>-source/flake.nix
nix run nixpkgs#python3 -- /nix/store/<hash>-source/ip-allocate.py <those flags> luni peers.json
```

Read two things off the output: the address it would actually assign (which may sit in
a different subnet from the one routed to you today), and whether it *preserves* an
explicit `ipv4` field. This one strips `ipv4`/`ipv6` from every non-controller peer and
re-allocates, so a hand-pinned peer address cannot survive the next regeneration — an
out-of-band address can exist only as a far-side route, never in the data.

**A name lookup is not a membership test.** When the zone derives names from keys (a
base32 encoding of the public key, say), a registered member returns NXDOMAIN for its
plain hostname too. Resolve one you know is registered before reading absence as
evidence.

## Probe discipline

- **ICMP is not a port test.** A ping timeout says nothing about TCP; a reply
  says nothing about whether the port is open.
- Probe with the protocol: `nc -vz -w 3 <host> <port>`, the service's own client, or
  `curl` for HTTP. **Give `nc` its own `-w`; never wrap it in `timeout`** — the wrapper
  kills it before it prints its verdict, so a timeout, a refusal and a success all
  arrive as the same silence, and a decisive probe reports nothing. `nc -vzu` is worse
  for UDP: it prints `succeeded` whether or not anything is listening.
- Probe the target **from itself** first — `nc -zv <its own tunnel address>
  <port>`. Success there isolates the fault to the path; failure to the listener.
- Report a source→port pair, never "the service is up".
- A cleartext protocol (MQTT without `cafile`/`certfile`) puts the credential on
  the wire in the clear the moment reachability works. Say that before widening
  reach, and prefer TLS settings over opening more of the network.
