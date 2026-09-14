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
argv mode cannot be filtered or guarded, so it allows only `status`.

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
# visible_since_utc must fall in this window. A typo that moves it earlier would expose
# old rows whose destination happens to be an assistant handle.
CUTOFF_FLOOR_UTC = "2026-09-13T00:00:00Z"

# chats/history/watch print plain text the visibility filter cannot check.
ARGV_SUBCOMMANDS = {"status"}
RPC_METHODS = {
    "initialize",
    "status",
    "chats.list",
    "messages.history",
    "messages.after",
    "watch.subscribe",
    "watch.unsubscribe",
    "send",
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


# Attachment switches set to false only turn a feature OFF, so they are safe.
# Set to true they are still denied: attachments stay off until designed for.
OFF_SWITCHES = {"attachments", "convert_attachments"}
# imsg send aliases for a threaded-reply target.
REPLY_KEYS = ("reply_to", "replyTo", "reply_to_guid", "message_guid")
# Fields of an imsg delivery-failure error that carry the reason, not message data.
DELIVERY_KEYS = ("retry_safe", "disposition", "transport", "operation", "detail")
CHAT_TARGET_KEYS = ("chat_id", "chat_identifier", "chat_guid")
SMS_FALLBACK_KEYS = ("allow_sms_fallback", "allowSMSFallback")
ONE_TO_ONE_STYLE = 45  # chat.style for a 1:1 chat; 43 is a group
OSASCRIPT = "/usr/bin/osascript"
SEND_TIMEOUT = 20
DELIVERY_WAIT = 8  # seconds to find the sent row in chat.db
# The brain may ask for any of these, but the gate picks the real service itself.
ALLOWED_SERVICES = {"auto", "imessage", "sms"}
PHONE_HANDLE = re.compile(r"\+\d{7,15}")
# Services that arrive through the assistant iPhone as carrier text messages.
TEXT_SERVICES = {"SMS", "RCS"}
COUNTRY_CODE = "63"  # Philippines: local numbers look like 09XXXXXXXXX


def e164(handle):
    """Best-effort E.164 form of a phone handle, else None."""
    digits = re.sub(r"[\s\-()]", "", handle or "")
    if re.fullmatch(r"\+\d{7,15}", digits):
        return digits
    if re.fullmatch(r"0\d{10}", digits):
        return "+" + COUNTRY_CODE + digits[1:]
    if re.fullmatch(r"%s\d{10}" % COUNTRY_CODE, digits):
        return "+" + digits
    return None
# Same AppleScript path as `imsg send` when it has no existing chat: address the buddy on
# the chosen service. Recipient, text, and service arrive as arguments, never in the script.
# The phase tells the gate whether Messages was asked to send before an error happened.
BUDDY_SEND_SCRIPT = """on run argv
    set theRecipient to item 1 of argv
    set theMessage to item 2 of argv
    set dryRun to item 3 of argv
    set theService to item 4 of argv
    set phase to "pre_dispatch"
    try
        tell application "Messages"
            if theService is "sms" then
                set targetService to first service whose service type is SMS
            else
                set targetService to first service whose service type is iMessage
            end if
            set targetBuddy to buddy theRecipient of targetService
            if dryRun is "1" then
                get id of targetBuddy
                return "dry-run ok"
            end if
            set phase to "dispatch_started"
            send theMessage to targetBuddy
        end tell
    on error errMsg number errNum
        return "error " & phase & " " & errNum
    end try
    return "sent"
end run
"""


def buddy_send(handle, text, service="imessage", dry_run=False):
    """Send one message to a handle over "imessage" or "sms".

    Returns (status, detail). status is "sent", "pre_dispatch" (nothing was sent, safe to
    try another way), or "unknown" (Messages may have sent it; do not retry). detail never
    holds the handle or the text.
    """
    try:
        done = subprocess.run([OSASCRIPT, "-", handle, text, "1" if dry_run else "0",
                               "sms" if service == "sms" else "imessage"],
                              input=BUDDY_SEND_SCRIPT.encode(), capture_output=True,
                              timeout=SEND_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "unknown", "osascript timed out"
    except OSError:
        return "pre_dispatch", "osascript could not start"
    out = done.stdout.decode("utf-8", "replace").strip()[:80]
    if done.returncode != 0:
        number = re.search(r"\((-?\d+)\)", done.stderr.decode("utf-8", "replace"))
        return "unknown", "osascript exit %d, error %s" % (
            done.returncode, number.group(1) if number else "unknown")
    if out == "sent" or out.startswith("dry-run "):
        return "sent", out
    match = re.fullmatch(r"error (pre_dispatch|dispatch_started) (-?\d+)", out)
    if match:
        status = "pre_dispatch" if match.group(1) == "pre_dispatch" else "unknown"
        return status, "AppleScript error %s" % match.group(2)
    return "unknown", "unexpected osascript output"


def risky_key(value):
    """Return the first key name that points at files or attachments, or None."""
    if isinstance(value, dict):
        for k, v in value.items():
            name = str(k)
            if RISKY_NAME.search(name) and not (name in OFF_SWITCHES and v is False):
                return name
            found = risky_key(v)
            if found:
                return found
    elif isinstance(value, list):
        for v in value:
            found = risky_key(v)
            if found:
                return found
    return None



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
        self.sms_allowed = set()
        self.cutoff_ns = None
        try:
            with open(CONFIG) as fh:
                cfg = json.load(fh)
            handles = sorted({str(h).strip().lower() for h in cfg["assistant_handles"]} - {""})
            # Family numbers that may get SMS replies. Missing or bad -> no SMS at all.
            sms = cfg.get("sms_allowed_handles", [])
            self.sms_allowed = ({str(h).strip() for h in sms if isinstance(h, str)
                                 and PHONE_HANDLE.fullmatch(h.strip())}
                                if isinstance(sms, list) else set())
            since = calendar.timegm(time.strptime(cfg["visible_since_utc"], "%Y-%m-%dT%H:%M:%SZ"))
            floor = calendar.timegm(time.strptime(CUTOFF_FLOOR_UTC, "%Y-%m-%dT%H:%M:%SZ"))
            if since < floor or since > time.time() + 86400:
                raise ValueError("visible_since_utc outside the allowed window")
            self.cutoff_ns = (since - APPLE_EPOCH) * 1000000000
            self.handles = handles
            # chat.db stores the account as "E:<email>" or "P:<phone>".
            self.accounts = [("e:" if "@" in h else "p:") + h for h in handles]
        except (OSError, ValueError, KeyError, TypeError) as err:
            self.handles, self.accounts, self.cutoff_ns, self.sms_allowed = [], [], None, set()
            log("config", "visibility config unusable, all reads hidden: %s" % short(str(err)))
        self._conn = None
        self._lock = threading.Lock()

    def _select(self, sql, keys):
        with self._lock:
            return self._select_locked(sql, keys)

    def _connection(self):
        if self._conn is None:
            self._conn = sqlite3.connect("file:%s?mode=ro" % CHAT_DB, uri=True, timeout=5,
                                         check_same_thread=False)
        return self._conn

    def _select_locked(self, sql, keys):
        if not keys or not self.handles or self.cutoff_ns is None:
            return set()
        found = set()
        if self._conn is None:
            self._conn = sqlite3.connect("file:%s?mode=ro" % CHAT_DB, uri=True, timeout=5,
                                         check_same_thread=False)
        conn = self._conn
        try:
            for i in range(0, len(keys), SQL_CHUNK):
                chunk = keys[i:i + SQL_CHUNK]
                query = sql.format(keys=",".join("?" * len(chunk))) % self.MATCH.format(
                    accounts=",".join("?" * len(self.accounts)),
                    handles=",".join("?" * len(self.handles)))
                args = chunk + [self.cutoff_ns] + self.accounts + self.handles
                found.update(row[0] for row in conn.execute(query, args))
        except sqlite3.Error:
            # Reopen next time. The caller hides the data for this reply.
            self._conn = None
            conn.close()
            raise
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

    def one_to_one_handle(self, params):
        return self.eligible_target(params)[0]

    def eligible_target(self, params):
        """(handle, service of the latest inbound message) for a 1:1 chat the brain may send
        to, else (None, None). The service is "SMS" or "iMessage" as chat.db stores it.

        Allowed only if that person has sent at least one message to the assistant account
        after the switch (inbound, is_from_me = 0). The assistant's own outgoing messages
        do not count, so the brain cannot unlock a chat by messaging it first.
        """
        supplied = [k for k in CHAT_TARGET_KEYS if k in params]
        if len(supplied) != 1:
            return None, None
        key, value = supplied[0], params[supplied[0]]
        column = {"chat_id": "ROWID", "chat_identifier": "chat_identifier", "chat_guid": "guid"}[key]
        if key == "chat_id" and (not isinstance(value, int) or isinstance(value, bool)):
            return None, None
        if key != "chat_id" and not isinstance(value, str):
            return None, None
        if not self.handles or self.cutoff_ns is None:
            return None, None
        with self._lock:
            conn = self._connection()
            try:
                rows = conn.execute(
                    "select ROWID, chat_identifier from chat where %s = ? and style = ?" % column,
                    (value, ONE_TO_ONE_STYLE)).fetchall()
                identifiers = {r[1] for r in rows if r[1]}
                if len(identifiers) != 1:
                    return None, None
                handle = identifiers.pop()
                # Any 1:1 chat row for this handle (iMessage and SMS rows can both exist).
                all_rows = [r[0] for r in conn.execute(
                    "select ROWID from chat where chat_identifier = ? and style = ?",
                    (handle, ONE_TO_ONE_STYLE))]
                query = ("select m.service from chat_message_join j join message m on m.ROWID = j.message_id"
                         " where j.chat_id in (%s) and m.is_from_me = 0 and %s"
                         " order by m.date desc limit 1") % (
                    ",".join("?" * len(all_rows)),
                    self.MATCH.format(accounts=",".join("?" * len(self.accounts)),
                                      handles=",".join("?" * len(self.handles))))
                args = all_rows + [self.cutoff_ns] + self.accounts + self.handles
                inbound = all_rows and conn.execute(query, args).fetchone()
            except sqlite3.Error:
                self._conn = None
                conn.close()
                raise
        if not inbound:
            return None, None
        return handle, inbound[0]

    def reply_service(self, handle, last_inbound_service):
        """Reply on the service the person last used.

        Returns "imessage", "sms", or None (do not send). A carrier text (SMS or RCS) gets an
        SMS reply only for allowlisted family numbers. Anyone else who reached the assistant
        by text message gets NO reply: that is how strangers and short codes reach it.
        """
        if last_inbound_service in TEXT_SERVICES:
            return "sms" if e164(handle) in self.sms_allowed else None
        return "imessage"

    def sent_row(self, handle, since_ns, label):
        """(id, guid, error, is_sent) of an outgoing message to handle over the label service
        ("SMS" or "iMessage") newer than since_ns, else None."""
        with self._lock:
            conn = self._connection()
            query = ("select m.ROWID, m.guid, m.error, m.is_sent from message m join chat_message_join j"
                     " on j.message_id = m.ROWID join chat c on c.ROWID = j.chat_id"
                     " where c.chat_identifier = ? and c.style = ? and m.is_from_me = 1"
                     " and m.date >= ? and m.service = ?"
                     " and (lower(coalesce(m.destination_caller_id, '')) in (%s)"
                     " or (m.service = 'SMS' and c.service_name = 'SMS'))"
                     " order by m.date desc limit 1") % ",".join("?" * len(self.handles))
            try:
                return conn.execute(query, [handle, ONE_TO_ONE_STYLE, since_ns, label]
                                    + self.handles).fetchone()
            except sqlite3.Error:
                self._conn = None
                conn.close()
                return None

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

    def filter_result(self, result):
        """Filter by shape, never by which method the reply claims to answer."""
        if not isinstance(result, dict):
            return None if contains_content(result) else result
        if "chats" in result:
            chats = [c for c in result.get("chats") or [] if isinstance(c, dict)]
            allowed = self.visible_chat_ids([c.get("id") for c in chats])
            result["chats"] = [c for c in chats if c.get("id") in allowed]
        if "messages" in result:
            result["messages"] = self.filter_messages(result.get("messages") or [])
        rest = {k: v for k, v in result.items() if k not in ("chats", "messages")}
        if contains_content(rest):
            log("hide", "unexpected content keys in a result")
            return {k: result[k] for k in ("chats", "messages") if k in result}
        return result

    def filter_response(self, response):
        if "result" in response:
            response["result"] = self.filter_result(response["result"])
        error = response.get("error")
        if error is not None:
            # A JSON-RPC error's "message" is error text, not an iMessage. Keep code and
            # message (short), log them so failures can be fixed, and drop "data", which
            # could echo a request or a message row.
            code = error.get("code") if isinstance(error, dict) else None
            text = error.get("message") if isinstance(error, dict) else None
            text = text[:300] if isinstance(text, str) else "error"
            data = error.get("data") if isinstance(error, dict) else None
            clean = {"code": code if isinstance(code, int) else -32000, "message": text}
            # imsg puts the reason in a short string "data" (e.g. "unknown send param: x").
            # Keep only a short string; drop objects that could hold message rows.
            if isinstance(data, str):
                clean["data"] = data[:300]
                reason = data[:200]
            elif isinstance(data, dict):
                # imsg delivery failures: retry_safe, disposition, transport, operation, detail.
                kept = {k: (v[:300] if isinstance(v, str) else v) for k, v in data.items()
                        if k in DELIVERY_KEYS and isinstance(v, (str, bool, int))}
                if kept:
                    clean["data"] = kept
                reason = json.dumps(kept)[:300] if kept else "-"
            else:
                reason = "-"
            # Quoted strings in errors can hold handles or text; keep them out of the log.
            log("imsg-error", "code=%s %s | %s" % (short(code), re.sub(r'"[^"]*"', '"..."', text[:120]),
                                                   re.sub(r'"[^"]*"', '"..."', reason)))
            response["error"] = clean
        rest = {k: v for k, v in response.items() if k not in ("result", "error")}
        if contains_content(rest):
            log("hide", "content outside result")
            return {k: response[k] for k in ("jsonrpc", "id", "result", "error") if k in response}
        return response

    def filter_notification(self, note):
        params = note.get("params")
        if note.get("method") == "message" and isinstance(params, dict):
            kept = self.filter_messages([params.get("message")])
            if not kept:
                return None
            others = {k: v for k, v in note.items() if k != "params"}
            other_params = {k: v for k, v in params.items() if k != "message"}
            if contains_content(others) or contains_content(other_params):
                log("hide", "content outside params.message")
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
    if args in (["--help"], ["-h"]):
        # OpenClaw may probe `imsg rpc --help`. It prints usage text only, no data.
        os.execv(IMSG, [IMSG, "rpc", "--help"])
    check_rpc_args(args)
    visibility = Visibility()
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
        is_response = "method" not in message
        try:
            if is_response:
                message = visibility.filter_response(message)
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
                reject(None, "request id must be an integer or a string")
                continue
            method = request.get("method")
            if not isinstance(method, str) or method not in RPC_METHODS:
                reject(request_id, "method %s is not allowed" % short(method))
                continue
            bad_key = risky_key(request)
            if bad_key:
                reject(request_id, "file or path parameter %s in %s" % (short(bad_key), short(method)))
                continue
            params = request.get("params")
            if method == "send" and isinstance(params, dict):
                # Threaded replies need imsg's bridge (SIP off + dylib), which this Mac does
                # not have, and imsg then refuses the whole send. Send a plain message.
                stripped = [k for k in REPLY_KEYS if k in params]
                for k in stripped:
                    del params[k]
                if stripped:
                    log("strip", "removed %s from send (no bridge on this Mac)" % ",".join(stripped))
                # The brain may name a service, but the gate picks it: reply on the service
                # the person last used, SMS only for allowlisted family numbers.
                service = params.get("service", "auto")
                if not isinstance(service, str) or service not in ALLOWED_SERVICES:
                    reject(request_id, "service must be auto, imessage, or sms")
                    continue
                # imsg resolves every 1:1 send to the old chat in chat.db, which Messages
                # cannot find after the Apple ID switch (AppleScript -1728). The gate sends
                # itself, and ONLY to a 1:1 chat whose person has messaged the assistant.
                # Nothing is ever forwarded to imsg's send.
                target = dict((k, params[k]) for k in CHAT_TARGET_KEYS if k in params)
                if not target and isinstance(params.get("to"), str):
                    target = {"chat_identifier": params["to"].strip()}
                try:
                    handle, last_service = (visibility.eligible_target(target) if target
                                            else (None, None))
                except sqlite3.Error:
                    handle, last_service = None, None
                text = params.get("text")
                if not handle:
                    reject(request_id, "send allowed only to a 1:1 chat that messaged the assistant")
                    continue
                if not isinstance(text, str) or not text.strip():
                    reject(request_id, "send needs text")
                    continue
                channel = visibility.reply_service(handle, last_service)
                if channel is None:
                    reject(request_id, "no reply: this person reached the assistant by text message "
                                       "and is not on the family SMS list")
                    continue
                started_ns = (int(time.time()) - APPLE_EPOCH - 2) * 1000000000
                status, detail = buddy_send(handle, text, channel)
                if status == "pre_dispatch" and channel == "sms":
                    # Nothing was sent, so trying iMessage cannot cause a double message.
                    log("sms", "SMS not possible (%s); falling back to iMessage" % detail)
                    channel = "imessage"
                    status, detail = buddy_send(handle, text, channel)
                label = "SMS" if channel == "sms" else "iMessage"
                row = None
                if status == "sent":
                    # Wait for the row, then for Messages to mark it sent or failed. An SMS goes
                    # through the assistant iPhone, so a failure can show up a few seconds later.
                    for _ in range(DELIVERY_WAIT * 2):
                        row = visibility.sent_row(handle, started_ns, label)
                        if row and (row[2] or row[3]):
                            break
                        time.sleep(0.5)
                if status == "sent" and row and row[2]:
                    status, detail = "unknown", "Messages reported delivery error %s" % row[2]
                    row = None
                if status == "sent" and row:
                    log("direct-send", "ok (1:1, %s, %d chars, row %d%s)" % (
                        label, len(text), row[0], "" if row[3] else ", not yet marked sent"))
                    result = {"jsonrpc": "2.0", "id": request_id,
                              "result": {"ok": True, "transport": "applescript",
                                         "service": label, "id": row[0],
                                         "guid": row[1], "message_id": row[1]}}
                elif status == "pre_dispatch":
                    log("direct-send", "failed before sending (%s): %s" % (label, detail))
                    result = {"jsonrpc": "2.0", "id": request_id,
                              "error": {"code": -32603, "message": "Delivery failed before dispatch",
                                        "data": {"transport": "applescript", "operation": "send",
                                                 "retry_safe": True, "disposition": "not_started",
                                                 "detail": detail}}}
                else:
                    reason = "not found in chat.db after send" if status == "sent" else detail
                    log("direct-send", "outcome unknown (%s): %s" % (label, reason))
                    # Messages may still deliver after a timeout or a late error, so a retry
                    # could send twice.
                    result = {"jsonrpc": "2.0", "id": request_id,
                              "error": {"code": -32001, "message": "Delivery outcome unknown",
                                        "data": {"transport": "applescript", "operation": "send",
                                                 "retry_safe": False, "disposition": "unknown",
                                                 "detail": reason}}}
                try:
                    write_line((json.dumps(result) + "\n").encode())
                except OSError:
                    finish(141)
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
