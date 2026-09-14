"""The brain-control tick: one launchd invocation's worth of work.

Runs the failover decision step, then the reminder clock step, wiring the
pure logic in failover.py and clock.py to real files, ssh, and HTTP calls.
Local files (lease, mode, state) go through brain_control.senders
directly; `io` carries only the external I/O calls (health checks,
docker, ssh, hooks) so tests can fake them out.

State is always saved after each step, even if that step raised, so any
sends that already happened before the failure are not lost on the next
tick. Never log message text, handles, the hooks token, or the Syncthing
API key.
"""

import copy
import fcntl
import json
import os
from datetime import datetime, timezone

from . import clock
from . import failover
from . import schedule
from . import senders as _senders

LOG_MAX_BYTES = 1024 * 1024
LOG_KEEP_LINES = 2000
CONTAINER_NAME = "openclaw"


def _log(log_path, event, detail=""):
    line = "%s %s %s\n" % (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), event, detail,
    )
    try:
        with open(log_path, "a") as f:
            f.write(line)
        _rotate_log(log_path)
    except Exception:
        pass


def _rotate_log(log_path):
    try:
        if os.path.getsize(log_path) <= LOG_MAX_BYTES:
            return
        with open(log_path, "r") as f:
            lines = f.readlines()
        tail = lines[-LOG_KEEP_LINES:]
        _senders.write_atomic(log_path, "".join(tail), mode=0o600)
    except Exception:
        pass


def _load_state(state_path, log_path):
    raw = _senders.read_text(state_path, "")
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        bad_path = "%s.bad-%d" % (state_path, int(datetime.now(timezone.utc).timestamp()))
        try:
            os.replace(state_path, bad_path)
        except OSError:
            pass
        _log(log_path, "error", "corrupt_state")
        return {}


def _save_state(state_path, st):
    _senders.write_atomic(state_path, json.dumps(st), mode=0o600)


def _read_env(env_path):
    raw = _senders.read_text(env_path, "")
    env = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def _clean_lease(raw):
    value = (raw or "").strip()
    return value if value in ("pc", "mac") else "pc"


def _send_notice(io, cfg, mark_handle, text, log_path):
    if not mark_handle:
        # No Mark handle configured: log that a notice was skipped, never
        # the notice text itself.
        _log(log_path, "notice_skipped", "no_mark_handle")
        return False
    return io.gate_send(
        cfg["clock_ssh_key"], cfg["clock_known_hosts"], cfg["clock_ssh_target"],
        mark_handle, text,
    )


def _run_failover(cfg, io, st, mode, lease, mark_handle, log_path):
    fst = st["failover"]
    backup = copy.deepcopy(fst)
    lease_ok = True

    try:
        if mode == "off":
            pc_ok = False
            pc_sync = False
            mac_running = False
        else:
            pc_ok = io.pc_healthy(cfg["pc_health_url"])
            pc_sync = io.syncthing_in_sync(
                cfg["syncthing_config"], cfg["syncthing_folder"], cfg["pc_device_name"],
            )
            mac_running = io.docker_running(cfg["docker"], CONTAINER_NAME)

        inp = failover.Inputs(
            mode=mode, lease=lease, pc_healthy=pc_ok, pc_in_sync=pc_sync,
            mac_running=mac_running,
        )
        acts = failover.step(inp, fst)

        if acts.lease:
            try:
                _senders.write_atomic(cfg["lease_path"], acts.lease + "\n", mode=0o644)
            except Exception:
                # Lease write failed: undo this tick's counter changes so
                # the next tick retries from the same state, and skip the
                # docker action and notices that assumed the write worked.
                fst.clear()
                fst.update(backup)
                lease_ok = False
                _log(log_path, "error", "lease_write")

        if lease_ok:
            if acts.docker == "up":
                io.docker_compose(cfg["docker"], cfg["repo_dir"], "up")
            elif acts.docker == "stop":
                io.docker_compose(cfg["docker"], cfg["repo_dir"], "stop")

            for text in acts.notices:
                _send_notice(io, cfg, mark_handle, text, log_path)
    finally:
        _save_state(cfg["state_path"], st)


def _run_clock(cfg, io, st, now, lease, allow, mark_handle, log_path):
    token = _senders.read_text(cfg["hooks_token_path"], "").strip()

    def send_text(handle, text):
        return io.gate_send(
            cfg["clock_ssh_key"], cfg["clock_known_hosts"], cfg["clock_ssh_target"],
            handle, text,
        )

    def send_smart(lease_value, payload):
        url = cfg["hooks_urls"].get(_clean_lease(lease_value))
        if not url:
            return False
        return io.hook_agent(url, token, payload)

    def notify_mark(text):
        _send_notice(io, cfg, mark_handle, text, log_path)
        return True

    def log(event, detail):
        _log(log_path, event, detail)

    try:
        clock.run(
            cfg["reminders_dir"], st["clock"], now, lease, allow,
            send_text, send_smart, notify_mark, log,
        )
    finally:
        _save_state(cfg["state_path"], st)


def tick(cfg, now=None, io=None):
    if io is None:
        io = _senders
    if now is None:
        now = datetime.now(timezone.utc)

    log_path = cfg["log_path"]

    lock_dir = os.path.dirname(cfg["lock_path"]) or "."
    try:
        if lock_dir:
            os.makedirs(lock_dir, exist_ok=True)
    except OSError:
        pass

    lock_file = open(cfg["lock_path"], "a")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        lock_file.close()
        return

    try:
        st = _load_state(cfg["state_path"], log_path)
        st.setdefault("failover", {})
        st.setdefault("clock", {})

        env = _read_env(cfg["env_path"])
        allow = schedule.parse_allowlist(env.get("IMESSAGE_ALLOW_FROM", ""))
        mark_handle = env.get(cfg["mark_handle_env"]) or None

        mode = _senders.read_text(cfg["mode_path"], "off").strip()
        lease = _clean_lease(_senders.read_text(cfg["lease_path"], "pc"))

        try:
            _run_failover(cfg, io, st, mode, lease, mark_handle, log_path)
        except Exception as exc:
            _log(log_path, "error", "failover %s" % type(exc).__name__)

        lease = _clean_lease(_senders.read_text(cfg["lease_path"], "pc"))

        try:
            _run_clock(cfg, io, st, now, lease, allow, mark_handle, log_path)
        except Exception as exc:
            _log(log_path, "error", "clock %s" % type(exc).__name__)
    finally:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
        except Exception:
            pass
        lock_file.close()


if __name__ == "__main__":
    config_path = os.path.expanduser("~/.brain-control/config.json")
    with open(config_path, "r") as _f:
        _cfg = json.load(_f)
    tick(_cfg)
