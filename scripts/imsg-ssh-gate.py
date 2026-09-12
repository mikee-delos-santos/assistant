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
    "initialize",
    "status",
    "chats.list",
    "messages.history",
    "messages.after",
    "watch.subscribe",
    "watch.unsubscribe",
    "send",
    "handles.check",
}
RPC_FLAGS = {"-v", "--verbose", "-j", "--json", "--json-output", "--jsonOutput"}
LOG_LEVEL_FLAGS = {"--log-level", "--logLevel"}
LOG_LEVELS = {"trace", "verbose", "debug", "info", "warning", "error", "critical"}
MAX_LINE = 1024 * 1024
# Option names and JSON keys that point at files or change what imsg loads.
RISKY_NAME = re.compile(r"file|path|db|dylib|attach", re.IGNORECASE)


def short(value):
    text = repr(value)
    return text if len(text) <= 80 else text[:77] + "..."


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
        deny("subcommand %s is not allowed" % short(sub))
    for arg in args[1:]:
        if risky_option(arg):
            deny("option %s is not allowed" % short(arg.split("=", 1)[0]))
    os.execv(IMSG, [IMSG] + args)


def check_rpc_args(args):
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in RPC_FLAGS:
            i += 1
            continue
        name, eq, value = arg.partition("=")
        if name in LOG_LEVEL_FLAGS:
            if not eq:
                value = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            if value not in LOG_LEVELS:
                deny("rpc log level %s is not allowed" % short(value))
            i += 1
            continue
        deny("rpc option %s is not allowed" % short(name))


def reject_duplicate_keys(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def reject_constant(name):
    raise ValueError("constant %s" % name)


def parse_request(raw):
    # Parse strictly, then forward our own re-encoding. imsg's JSON parser keeps the
    # FIRST duplicate key and Python keeps the LAST, so forwarding the raw bytes would
    # let a request pass the checks as one method and run as another.
    return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                      parse_constant=reject_constant)


def run_rpc(args):
    check_rpc_args(args)
    child = subprocess.Popen([IMSG, "rpc"] + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    out = sys.stdout.buffer
    out_lock = threading.Lock()

    def finish(code):
        try:
            child.kill()
        except OSError:
            pass
        os._exit(code)

    def write_line(data):
        with out_lock:
            out.write(data)
            out.flush()

    def pump_child_output():
        try:
            for line in iter(child.stdout.readline, b""):
                write_line(line)
        except OSError:
            # The SSH client is gone. Stop imsg instead of letting it block on a full pipe.
            finish(141)
        # imsg exited. Exit too, so the brain sees the bridge close and can restart it.
        finish(child.wait())

    pump = threading.Thread(target=pump_child_output, daemon=True)
    pump.start()

    def reject(request_id, reason):
        log("deny-rpc", reason)
        # Always answer, with "id": null when there is no usable id, so a client that
        # waits for a reply does not hang.
        error = {"jsonrpc": "2.0", "id": request_id,
                 "error": {"code": -32601, "message": "imsg-ssh-gate: " + reason}}
        try:
            write_line((json.dumps(error) + "\n").encode())
        except OSError:
            finish(141)

    while True:
        raw = sys.stdin.buffer.readline(MAX_LINE + 1)
        if not raw:
            break
        if len(raw) > MAX_LINE:
            log("deny-rpc", "line longer than %d bytes" % MAX_LINE)
            finish(126)
        if not raw.strip():
            continue
        request_id = None
        try:
            request = parse_request(raw)
            if not isinstance(request, dict):
                reject(None, "batch or non-object request")
                continue
            request_id = request.get("id")
            if not isinstance(request_id, (int, str)) or isinstance(request_id, bool):
                request_id = None
            method = request.get("method")
            if not isinstance(method, str) or method not in RPC_METHODS:
                reject(request_id, "method %s is not allowed" % short(method))
                continue
            if has_risky_key(request):
                reject(request_id, "file or path parameter in %s" % short(method))
                continue
            line = json.dumps(request, separators=(",", ":"), allow_nan=False) + "\n"
        except Exception as err:
            # Any surprise (deep nesting, 1e400, odd types) is a denial, never a crash.
            reject(request_id, "bad request: %s" % short("%s: %s" % (type(err).__name__, err)))
            continue
        try:
            child.stdin.write(line.encode())
            child.stdin.flush()
        except OSError:
            break

    try:
        child.stdin.close()
    except OSError:
        pass
    try:
        code = child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        code = 124
    # Let the pump write imsg's last lines. It exits the process itself at EOF.
    pump.join(timeout=5)
    finish(code)


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
