#!/bin/sh
# Brice's single, fixed entrypoint to start a remote-enabled Claude Code session for Mark.
#
#   claude-launch <project>     project = infopathy | mindr | work
#   claude-launch list          list the Mac projects the launch gate accepts
#
# infopathy runs on THIS PC: drop a trigger the Windows host watcher consumes to open a
# visible Warp + claude. mindr/work run on the Mac: call the locked launch gate over SSH
# with the separate brice-launch key (it accepts only `list` and `launch <key>`).
#
# This is not a general shell. Only these keys do anything; anything else is refused.
# Remote-control sessions are tied to Mark's claude.ai account, so only Mark can attach.
set -eu

ssh_gate() {
  exec ssh -T -i "$LAUNCH_SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
    -o UserKnownHostsFile="$LAUNCH_SSH_KNOWN_HOSTS" -o StrictHostKeyChecking=yes \
    -o ServerAliveInterval=30 -- "$LAUNCH_SSH_TARGET" "$1"
}

project="${1:-}"
case "$project" in
  infopathy)
    : > /home/node/.launch-triggers/infopathy
    echo '{"ok":true,"project":"infopathy","note":"launch requested on the PC; open the Claude app - do not assume it is ready yet"}'
    ;;
  mindr|work)
    ssh_gate "launch $project"
    ;;
  list)
    ssh_gate "list"
    ;;
  *)
    echo '{"ok":false,"error":"unknown project; allowed: infopathy, mindr, work"}' >&2
    exit 2
    ;;
esac
