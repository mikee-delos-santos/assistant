#!/bin/sh
# Brice's single, fixed entrypoint to start a remote-enabled Claude Code session for Mark.
#
#   claude-launch <project>     project = infopathy | mindr | work
#   claude-launch list          list the Mac projects the launch gate accepts
#   claude-launch where         print which host this brain runs on (BRAIN_HOST)
#
# infopathy runs on the PC: drop a trigger the Windows host watcher consumes to open a
# visible Warp + claude. mindr/work run on the Mac: call the locked launch gate over SSH
# with the separate brice-launch key (it accepts only `list` and `launch <key>`).
#
# BRAIN_HOST (per-host .env, never synced) says which machine runs this brain: pc or mac.
# The same image runs on both, and the container cannot tell them apart by itself.
# Unset means pc, so a PC .env written before this variable existed keeps working.
#
# This is not a general shell. Only these keys do anything; anything else is refused.
# Remote-control sessions are tied to Mark's claude.ai account, so only Mark can attach.
set -eu

# Trim spaces and a Windows CR, and lowercase, so "PC" or "pc\r" from a hand-edited .env
# still work. Only infopathy and where need a valid value; mindr/work do not depend on it.
brain_host=$(printf '%s' "${BRAIN_HOST:-pc}" | tr -d ' \t\r' | tr 'A-Z' 'a-z')
[ -n "$brain_host" ] || brain_host=pc

require_brain_host() {
  case "$brain_host" in
    pc|mac) ;;
    *)
      echo '{"ok":false,"error":"BRAIN_HOST must be pc or mac"}' >&2
      exit 2
      ;;
  esac
}

fail() {
  # Only a known value goes into the JSON, so a strange BRAIN_HOST cannot break it.
  case "$brain_host" in pc|mac) shown=$brain_host ;; *) shown=invalid ;; esac
  printf '{"ok":false,"brain_host":"%s","error":"%s"}\n' "$shown" "$1" >&2
  exit 1
}

ssh_gate() {
  # A brain without launch key settings must say so plainly, not die on an unset variable.
  if [ -z "${LAUNCH_SSH_KEY:-}" ] || [ -z "${LAUNCH_SSH_KNOWN_HOSTS:-}" ] \
     || [ -z "${LAUNCH_SSH_TARGET:-}" ] || [ ! -r "$LAUNCH_SSH_KEY" ]; then
    fail "launch key is not set up on this brain; Mac sessions can only be launched when the brain has its launch key"
  fi
  # The gate prints its own JSON. Exit 255 means ssh itself failed (for example the Mac
  # does not accept this brain's key), so turn that into JSON too.
  if ssh -T -i "$LAUNCH_SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
    -o UserKnownHostsFile="$LAUNCH_SSH_KNOWN_HOSTS" -o StrictHostKeyChecking=yes \
    -o ServerAliveInterval=30 -- "$LAUNCH_SSH_TARGET" "$1"; then
    exit 0
  else
    rc=$?
  fi
  [ "$rc" -ne 255 ] || fail "could not reach the Mac launch gate over ssh (key not accepted or Mac unreachable)"
  exit "$rc"
}

project="${1:-}"
case "$project" in
  infopathy)
    # The trigger folder is only watched on the PC. On the Mac brain the file would
    # sit there unread while Brice reports success.
    require_brain_host
    [ "$brain_host" = "pc" ] || fail "infopathy launches only work when the PC is the brain; the Mac is the brain now"
    : > /home/node/.launch-triggers/infopathy
    echo '{"ok":true,"project":"infopathy","note":"launch requested on the PC; open the Claude app - do not assume it is ready yet"}'
    ;;
  mindr|work)
    ssh_gate "launch $project"
    ;;
  list)
    ssh_gate "list"
    ;;
  where)
    require_brain_host
    printf '{"ok":true,"brain_host":"%s"}\n' "$brain_host"
    ;;
  *)
    echo '{"ok":false,"error":"unknown project; allowed: infopathy, mindr, work, list, where"}' >&2
    exit 2
    ;;
esac
