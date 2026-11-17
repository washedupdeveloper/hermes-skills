#!/usr/bin/env bash
# Gateway reachability triage — run INSIDE the WSL guest. Read-only.
#
# Discriminates, in one pass, between:
#   distro stopped / nothing listening -> connect is REFUSED (fast)
#   service dead                       -> port absent from `ss`
#   local delivery broken              -> every connect TIMES OUT, even to a
#     surely-closed port, and `ip rule` is missing "0: from all lookup local"
#
# Invoke (strip CR first — this file is written CRLF on Windows; the skills dir
# from the guest is /mnt/c/ + the path skill_view reports):
#   wsl.exe -d <distro> -- /bin/bash -c "tr -d '\r' < /mnt/c/<skills-dir>/hermes-wsl-backend/scripts/gateway-reachability-probe.sh > /tmp/gwprobe.sh"
#   wsl.exe -d <distro> -- /bin/bash /tmp/gwprobe.sh [port]     # port defaults to 9119
set -u
PORT="${1:-9119}"

echo "== identity =="
whoami; date
echo
echo "== hermes backend service =="
systemctl --user is-active hermes-serve.service 2>&1
systemctl --user status hermes-serve.service --no-pager 2>&1 | sed -n '1,8p'
echo
echo "== listeners =="
ss -tlnp 2>/dev/null | head -20
echo
echo "== policy rules — MUST contain: 0: from all lookup local =="
ip rule show 2>&1
echo
echo "== route lookups — expect: local 127.0.0.1 dev lo src 127.0.0.1 =="
ip route get 127.0.0.1 2>&1
ip route get 10.255.255.254 2>&1   # WSL DNS proxy — also a loopback address
echo
echo "== port matrix — fast fail = refused (listener absent); ~4000ms = packets dying =="
probe_port() {
  local p="$1" t0 t1 ms
  t0=$(date +%s%N)
  if timeout 4 bash -c "exec 3<>/dev/tcp/127.0.0.1/$p" 2>/dev/null; then
    echo "127.0.0.1:$p OPEN"
  else
    t1=$(date +%s%N); ms=$(( (t1 - t0) / 1000000 ))
    echo "127.0.0.1:$p FAILED after ${ms}ms"
  fi
}
probe_port "$PORT"   # the gateway
probe_port 22        # a listener that must exist
probe_port 9999      # surely closed — the control
echo
echo "== counters before =="
grep -E 'lo:|eth0:|loopback0:' /proc/net/dev
( timeout 5 bash -c "exec 3<>/dev/tcp/127.0.0.1/$PORT" 2>/dev/null ) &
BG=$!
sleep 2
echo "== sockets during the hang (SYN-SENT sourced from the eth0 address = misrouted local connect) =="
ss -tan 2>&1 | grep -E 'LISTEN|SYN-SENT' | head -12
wait "$BG" 2>/dev/null
echo "== counters after — lo frozen while eth0 moves = local traffic leaving via eth0 =="
grep -E 'lo:|eth0:|loopback0:' /proc/net/dev
echo
echo "== recent system generations (a switch near the outage start is the suspect) =="
ls -lt --time-style=+'%F %T' /nix/var/nix/profiles/system-*-link 2>/dev/null | head -4
systemctl --user show hermes-serve.service -p ExecMainStartTimestamp 2>&1
echo
echo "== networkd tail (restarts, link churn) =="
journalctl -b --no-pager -u systemd-networkd 2>&1 | tail -15
echo
echo "== if the local rule is missing =="
echo "  correlate:    journalctl -b --since '<switch HH:MM>' --until '<+2 min>' --no-pager | tail -80"
echo "  what changed: nix store diff-closures /nix/var/nix/profiles/system-<N-1>-link /nix/var/nix/profiles/system-<N>-link"
echo "  restore:      sudo ip rule add pref 0 from all lookup local"
echo "  verify:       ip route get 127.0.0.1     # must read: local 127.0.0.1 dev lo src 127.0.0.1"
echo "                curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:$PORT/api/health"
