#!/usr/bin/python3
"""SSH forced command for the imsg bridge key. Runs on the Mac.

authorized_keys points the brain's key at this script, so a login with that key
can run only a small, safe part of imsg. sshd has Full Disk Access, so imsg can read
any file; the gate must stop the brain from using imsg to read or send files.

Two modes:
- argv mode (`imsg chats`, `imsg send --text ...`): allowlisted subcommands only,
  and no option that takes a file, path, database, or dylib.
- rpc mode (`imsg rpc`, what OpenClaw uses): the gate starts `imsg rpc` itself and
  filters every newline-framed JSON-RPC request on stdin by method allowlist.
  A request with a file or path parameter anywhere in it is denied.

The gate never starts a shell. Denials are logged with the method or subcommand
name only, never message text, so the allowlist can be tuned from the log.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time

IMSG = "/opt/homebrew/bin/imsg"
LOG = os.path.expanduser("~/.imsg-bridge/gate.log")

ARGV_SUBCOMMANDS = {"chats", "history", "watch", "send", "status"}
RPC_METHODS = {
    "chats.list",
    "messages.history",
    "messages.after",
    "watch.subscribe",
    "watch.unsubscribe",
    "send",
    "handles.check",
}
# Option names and JSON keys that point at files or change what imsg loads.
RISKY_NAME = re.compile(r"file|path|db|dylib|attach", re.IGNORECASE)


def log(event, detail):
    try:
        with open(LOG, "a") as fh:
            fh.write("%s %s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), event, detail))
    except OSError:
        pass


def deny(reason):
    log("deny", reason)
    sys.stderr.write("imsg-ssh-gate: denied: %s\n" % reason)
    sys.exit(126)


def risky_option(arg):
    if not arg.startswith("-"):
        return False
    name = arg.lstrip("-").split("=", 1)[0]
    return bool(RISKY_NAME.search(name))


def has_risky_key(value):
    if isinstance(value, dict):
        return any(RISKY_NAME.search(str(k)) or has_risky_key(v) for k, v in value.items())
    if isinstance(value, list):
        return any(has_risky_key(v) for v in value)
    return False


def run_argv(args):
    sub = args[0]
    if sub not in ARGV_SUBCOMMANDS:
        deny("subcommand %r is not allowed" % sub)
    for arg in args[1:]:
        if risky_option(arg):
            deny("option %r is not allowed" % arg.split("=", 1)[0])
    os.execv(IMSG, [IMSG] + args)


def run_rpc(args):
    for arg in args:
        if arg not in ("-v", "--verbose") and not arg.startswith("--log-level"):
            deny("rpc option %r is not allowed" % arg.split("=", 1)[0])

    child = subprocess.Popen([IMSG, "rpc"] + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    out = sys.stdout.buffer
    out_lock = threading.Lock()

    def write_line(data):
        with out_lock:
            out.write(data)
            out.flush()

    def pump_child_output():
        for line in iter(child.stdout.readline, b""):
            write_line(line)

    pump = threading.Thread(target=pump_child_output, daemon=True)
    pump.start()

    def reject(request_id, reason):
        log("deny-rpc", reason)
        if request_id is None:
            return
        error = {"jsonrpc": "2.0", "id": request_id,
                 "error": {"code": -32601, "message": "imsg-ssh-gate: " + reason}}
        write_line((json.dumps(error) + "\n").encode())

    for raw in iter(sys.stdin.buffer.readline, b""):
        if not raw.strip():
            continue
        try:
            request = json.loads(raw)
        except ValueError:
            reject(None, "not JSON")
            continue
        if not isinstance(request, dict):
            reject(None, "batch or non-object request")
            continue
        request_id = request.get("id")
        method = request.get("method")
        if method not in RPC_METHODS:
            reject(request_id, "method %r is not allowed" % (method,))
            continue
        if has_risky_key(request.get("params")):
            reject(request_id, "file or path parameter in %r" % method)
            continue
        try:
            child.stdin.write(raw if raw.endswith(b"\n") else raw + b"\n")
            child.stdin.flush()
        except BrokenPipeError:
            break

    try:
        child.stdin.close()
    except BrokenPipeError:
        pass
    code = child.wait()
    pump.join(timeout=5)
    sys.exit(code)


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
    if len(argv) < 2:
        deny("imsg needs a subcommand")
    if argv[1] == "rpc":
        run_rpc(argv[2:])
    run_argv(argv[1:])


if __name__ == "__main__":
    main()
