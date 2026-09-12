#!/usr/bin/env bash
# imsg wrapper for the brain (OpenClaw channels.imessage.cliPath).
# Runs imsg on the Mac over SSH. The Mac side only allows imsg (scripts/imsg-ssh-gate.py).
#
# Settings come from the environment so the same file works on both brains:
#   IMSG_SSH_TARGET  PC brain: mikee@100.67.66.94   Mac brain: mikee@host.docker.internal
#   IMSG_SSH_KEY     private key path for that host (must be chmod 600 inside the container)
#   IMSG_SSH_KNOWN_HOSTS  known_hosts file that holds the Mac host key
set -euo pipefail

: "${IMSG_SSH_TARGET:?set IMSG_SSH_TARGET}"
: "${IMSG_SSH_KEY:?set IMSG_SSH_KEY}"
: "${IMSG_SSH_KNOWN_HOSTS:?set IMSG_SSH_KNOWN_HOSTS}"

# ssh joins arguments with spaces, so quote each one for the gate's shlex parser.
# Single quotes keep everything literal; an embedded ' becomes '\''.
# sed instead of ${var//} because bash 3.2 and bash 5 treat quotes there differently.
# The trailing "x" keeps trailing newlines that $(...) would otherwise strip.
quoted=""
for arg in "$@"; do
  esc=$(printf '%sx' "$arg" | sed "s/'/'\\\\''/g")
  quoted="$quoted '${esc%x}'"
done

exec ssh -T \
  -i "$IMSG_SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
  -o UserKnownHostsFile="$IMSG_SSH_KNOWN_HOSTS" -o StrictHostKeyChecking=yes \
  -o ServerAliveInterval=30 \
  "$IMSG_SSH_TARGET" "/opt/homebrew/bin/imsg${quoted}"
