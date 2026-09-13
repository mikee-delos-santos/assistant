#!/bin/bash
# Install the PC brain's SEPARATE launch key on the Mac, locked to the Claude launch gate.
# Usage: bash scripts/install-launch-key.sh <path to pc-brice-launch.pub>
# Run it yourself (it changes ~/.ssh/authorized_keys). It never touches the imsg key.
set -euo pipefail
PUB="${1:?usage: install-launch-key.sh <pc-brice-launch.pub>}"
AK="$HOME/.ssh/authorized_keys"
GATE="$HOME/.claude-launch/claude-launch-gate"
[ -x "$GATE" ] || { echo "gate not installed at $GATE"; exit 1; }

LINE=$(tr -d '\r' < "$PUB" | grep -v '^\s*$')
[ "$(printf '%s\n' "$LINE" | wc -l | tr -d ' ')" = "1" ] || { echo "expected exactly one key line"; exit 1; }
set -- $LINE
[ "$#" = "3" ] && [ "$1" = "ssh-ed25519" ] && [ "$3" = "brice-launch" ] || { echo "expected: ssh-ed25519 <key> brice-launch"; exit 1; }
printf '%s\n' "$LINE" | ssh-keygen -lf - >/dev/null || { echo "not a valid public key"; exit 1; }
# Refuse a key that is already used for anything else (for example the imsg key).
if grep -F "$2" "$AK" | grep -vq " brice-launch$"; then
  echo "this key is already installed for another purpose; refusing"; exit 1
fi

cp "$AK" "$AK.bak-$(date +%Y%m%d%H%M%S)"
grep -v " brice-launch$" "$AK" > "$AK.new" || true
echo "from=\"100.123.4.5\",restrict,command=\"$GATE\" ssh-ed25519 $2 brice-launch" >> "$AK.new"
mv "$AK.new" "$AK" && chmod 600 "$AK"
echo "--- installed. authorized_keys now:"
ssh-keygen -lf "$AK"
