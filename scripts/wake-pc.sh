#!/usr/bin/env bash
# Wake the PC (primary brain) on the LAN via a Wake-on-LAN magic packet (AS-33).
# Runs on the Mac. Only works when the Mac and PC share the same physical LAN -
# Tailscale cannot wake a powered-off machine by itself.
#
# Prereqs on the PC: enable Wake-on-LAN + "restore on power loss" in BIOS,
# allow "Wake on Magic Packet" in the NIC driver, and disable Fast Startup.
set -euo pipefail

# TODO: fill in the PC's wired (Ethernet) NIC MAC address.
PC_MAC="AA:BB:CC:DD:EE:FF"
# Subnet broadcast address (e.g. 192.168.1.255), or leave the global broadcast.
BROADCAST="255.255.255.255"

if command -v wakeonlan >/dev/null 2>&1; then
  exec wakeonlan -i "$BROADCAST" "$PC_MAC"
fi

# Pure-python fallback (no brew install needed).
python3 - "$PC_MAC" "$BROADCAST" <<'PY'
import socket, sys
mac = sys.argv[1].replace(":", "").replace("-", "")
if len(mac) != 12:
    sys.exit("PC_MAC must be a 6-byte MAC address")
bcast = sys.argv[2]
packet = bytes.fromhex("f" * 12 + mac * 16)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
s.sendto(packet, (bcast, 9))
print(f"Sent WoL magic packet to {mac} via {bcast}:9")
PY
