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

Visibility filter (rpc responses): Messages on this Mac used to be signed in to
Mark's personal Apple ID, and chat.db still holds that history. The gate passes only
messages on the assistant's own iMessage account (handles in
~/.imsg-bridge/assistant.json) sent or received after the switch. Every chat,
message, and watch notification that imsg returns is checked against chat.db.
If the config is missing or a check fails, the gate hides the data (fail closed).
argv mode cannot be filtered, so it allows only `send` and `status`.

The gate never starts a shell. Denials are logged with the method or subcommand
name only, never message text, so the allowlist can be tuned from the log.
"""
import calendar
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import threading
import time

IMSG = "/opt/homebrew/bin/imsg"
LOG = os.path.expanduser("~/.imsg-bridge/gate.log")
CONFIG = os.path.expanduser("~/.imsg-bridge/assistant.json")
CHAT_DB = os.path.expanduser("~/Library/Messages/chat.db")
APPLE_EPOCH = 978307200
# Keys that carry message content. Unknown output holding any of them is hidden.
CONTENT_KEYS = {"text", "message", "messages", "chats", "reply_to_text", "attachments"}
SQL_CHUNK = 500

# chats/history/watch print plain text the visibility filter cannot check.
ARGV_SUBCOMMANDS = {"send", "status"}
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


def contains_content(value):
    if isinstance(value, dict):
        return any(k in CONTENT_KEYS or contains_content(v) for k, v in value.items())
    if isinstance(value, list):
        return any(contains_content(v) for v in value)
    return False


class Visibility:
    """Which chat.db rows the brain may see: messages on the assistant account only."""

    MATCH = ("m.date >= ? and (lower(coalesce(m.account, '')) in ({accounts})"
             " or lower(coalesce(m.destination_caller_id, '')) in ({handles}))")

    def __init__(self):
        self.handles = []
        self.accounts = []
        self.cutoff_ns = None
        try:
            with open(CONFIG) as fh:
                cfg = json.load(fh)
            handles = sorted({str(h).strip().lower() for h in cfg["assistant_handles"]} - {""})
            since = time.strptime(cfg["visible_since_utc"], "%Y-%m-%dT%H:%M:%SZ")
            self.cutoff_ns = (calendar.timegm(since) - APPLE_EPOCH) * 1000000000
            self.handles = handles
            # chat.db stores the account as "E:<email>" or "P:<phone>".
            self.accounts = [("e:" if "@" in h else "p:") + h for h in handles]
        except (OSError, ValueError, KeyError, TypeError) as err:
            log("config", "visibility config unusable, all reads hidden: %s" % short(str(err)))

    def _select(self, sql, keys):
        if not keys or not self.handles or self.cutoff_ns is None:
            return set()
        found = set()
        conn = sqlite3.connect("file:%s?mode=ro" % CHAT_DB, uri=True, timeout=5)
        try:
            for i in range(0, len(keys), SQL_CHUNK):
                chunk = keys[i:i + SQL_CHUNK]
                query = sql.format(keys=",".join("?" * len(chunk))) % self.MATCH.format(
                    accounts=",".join("?" * len(self.accounts)),
                    handles=",".join("?" * len(self.handles)))
                args = chunk + [self.cutoff_ns] + self.accounts + self.handles
                found.update(row[0] for row in conn.execute(query, args))
        finally:
            conn.close()
        return found

    @staticmethod
    def _ints(values):
        return sorted({v for v in values if isinstance(v, int) and not isinstance(v, bool)})

    def visible_message_ids(self, ids):
        return self._select("select m.ROWID from message m where m.ROWID in ({keys}) and %s",
                            self._ints(ids))

    def visible_guids(self, guids):
        return self._select("select m.guid from message m where m.guid in ({keys}) and %s",
                            sorted({g for g in guids if isinstance(g, str)}))

    def visible_chat_ids(self, ids):
        return self._select(
            "select distinct j.chat_id from chat_message_join j join message m"
            " on m.ROWID = j.message_id where j.chat_id in ({keys}) and %s",
            self._ints(ids))

    def filter_messages(self, items):
        items = [m for m in items if isinstance(m, dict)]
        allowed = self.visible_message_ids([m.get("id") for m in items])
        kept = [m for m in items if m.get("id") in allowed]
        replies = self.visible_guids([m.get("reply_to_guid") for m in kept])
        for m in kept:
            # A new message can quote an old personal one. Hide the quote.
            if m.get("reply_to_guid") and m.get("reply_to_guid") not in replies:
                m["reply_to_text"] = None
                m["reply_to_sender"] = None
        return kept

    def filter_response(self, method, response):
        result = response.get("result")
        if not isinstance(result, dict):
            return response
        if method == "chats.list":
            chats = [c for c in result.get("chats") or [] if isinstance(c, dict)]
            allowed = self.visible_chat_ids([c.get("id") for c in chats])
            result["chats"] = [c for c in chats if c.get("id") in allowed]
        elif method in ("messages.history", "messages.after"):
            result["messages"] = self.filter_messages(result.get("messages") or [])
        elif contains_content(result):
            log("hide", "content in %s result" % short(method))
            response["result"] = {}
        return response

    def filter_notification(self, note):
        params = note.get("params")
        if note.get("method") == "message" and isinstance(params, dict):
            kept = self.filter_messages([params.get("message")])
            if not kept:
                return None
            params["message"] = kept[0]
            return note
        if contains_content(params):
            log("hide", "content in %s notification" % short(note.get("method")))
            return None
        return note


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
    visibility = Visibility()
    pending = {}
    pending_lock = threading.Lock()
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

    def filter_line(line):
        try:
            message = json.loads(line.decode("utf-8"))
        except ValueError:
            log("hide", "non-JSON line from imsg")
            return None
        if not isinstance(message, dict):
            log("hide", "non-object line from imsg")
            return None
        response_id = message.get("id")
        is_response = "id" in message and "method" not in message
        try:
            if is_response:
                with pending_lock:
                    method = pending.pop(json.dumps(response_id), None)
                message = visibility.filter_response(method, message)
            else:
                message = visibility.filter_notification(message)
                if message is None:
                    return None
            return (json.dumps(message, separators=(",", ":")) + "\n").encode()
        except Exception as err:
            log("hide", "filter error: %s" % short("%s: %s" % (type(err).__name__, err)))
            if not is_response:
                return None
            error = {"jsonrpc": "2.0", "id": response_id,
                     "error": {"code": -32000, "message": "imsg-ssh-gate: result hidden"}}
            return (json.dumps(error) + "\n").encode()

    def pump_child_output():
        try:
            for line in iter(child.stdout.readline, b""):
                filtered = filter_line(line)
                if filtered is not None:
                    write_line(filtered)
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
            if request_id is not None:
                with pending_lock:
                    pending[json.dumps(request_id)] = method
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
