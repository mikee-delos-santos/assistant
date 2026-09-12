#!/usr/bin/python3
"""SSH forced command for the imsg bridge key. Runs on the Mac.

authorized_keys points the brain's key at this script, so a login with that key
can run imsg and nothing else. It never starts a shell: the requested command is
split with shlex and passed straight to execv.
"""
import os
import shlex
import sys

IMSG = "/opt/homebrew/bin/imsg"
# `launch` injects a dylib into Messages.app. The brain never needs it.
BLOCKED_SUBCOMMANDS = {"launch"}


def deny(reason):
    sys.stderr.write("imsg-ssh-gate: denied: %s\n" % reason)
    sys.exit(126)


def main():
    original = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    if not original.strip():
        deny("no command (interactive login is not allowed)")
    try:
        argv = shlex.split(original)
    except ValueError as err:
        deny("cannot parse command: %s" % err)
    if argv[0] not in (IMSG, "imsg"):
        deny("only imsg may run")
    if len(argv) > 1 and argv[1] in BLOCKED_SUBCOMMANDS:
        deny("imsg %s is not allowed" % argv[1])
    os.execv(IMSG, [IMSG] + argv[1:])


if __name__ == "__main__":
    main()
