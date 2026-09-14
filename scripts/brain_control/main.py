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
from datetime import datetime, timedelta, timezone

from . import clock
from . import failover
from . import schedule
from . import senders as _senders

LOG_MAX_BYTES = 1024 * 1024
LOG_KEEP_LINES = 2000
CONTAINER_NAME = "openclaw"
GATE_NOTICE_INTERVAL = timedelta(hours=24)
GATE_NOTICE_TEXT = (
    "Failover is paused: add --brain pc / --brain mac to the gate lines in authorized_keys."
)
DOCKER_UP_FAILED_TEXT = "Failover: the Mac brain did not start. Check Docker on the Mac."


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
    # type: (str, str) -> tuple
    """The saved state dict, and whether it had to be recovered from a
    corrupt file (including a file that parses but isn't a JSON object -
    a state file's shape is always an object, so anything else is exactly
    as unusable as a parse error)."""
    raw = _senders.read_text(state_path, "")
    if not raw.strip():
        return {}, False
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("state file is not a JSON object")
        return parsed, False
    except ValueError:
        bad_path = "%s.bad-%d" % (state_path, int(datetime.now(timezone.utc).timestamp()))
        try:
            os.replace(state_path, bad_path)
        except OSError:
            pass
        _log(log_path, "error", "corrupt_state")
        return {}, True


def _save_state(state_path, st):
    _senders.write_atomic(state_path, json.dumps(st), mode=0o600)


def _strip_matching_quotes(value):
    """Strip one pair of surrounding quotes (" or '), same as a shell would.

    .env.example values like OPENCLAW_GATEWAY_TOKEN are meant to be
    plugged in unquoted, but people sometimes copy a quoted value from
    elsewhere; only a matching pair at both ends is stripped, so a lone
    or mismatched quote (probably part of the real value) is left alone.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
        return value[1:-1]
    return value


def _read_env(env_path):
    raw = _senders.read_text(env_path, "")
    env = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = _strip_matching_quotes(value.strip())
    return env


def _clean_lease(raw):
    value = (raw or "").strip()
    return value if value in ("pc", "mac") else "pc"


def _outcome_delivered(result):
    """Whether a gate_send-shaped result counts as delivered.

    gate_send returns "ok"/"retry"/"final"; older fakes still return a
    plain bool. Anything that is not clearly "ok" (or True) counts as
    not delivered - a notice is fire-and-forget, so there is no retry
    here, only a log entry, and never the notice text itself.
    """
    return result is True or result == "ok"


def _send_notice(io, cfg, mark_handle, text, log_path):
    if not mark_handle:
        # No Mark handle configured: the caller already logged
        # "config_missing mark_handle" once for this tick, so nothing
        # more to log here, never the notice text itself.
        return False
    result = io.gate_send(
        cfg["clock_ssh_key"], cfg["clock_known_hosts"], cfg["clock_ssh_target"],
        mark_handle, text,
    )
    if not _outcome_delivered(result):
        _log(log_path, "notice_undelivered", "")
    return result


def _gate_is_unfenced(authorized_keys_path):
    # type: (str) -> bool
    """Whether any imsg-ssh-gate line in authorized_keys lacks --brain.

    Such a line accepts connections without a role, so the gate cannot
    tell a pc/mac brain connection from a clock connection and fencing
    (ruling R13) does not apply. A file that cannot be read is treated
    the same way: fail safe, never assume the gate is fenced when that
    cannot actually be verified.
    """
    try:
        with open(authorized_keys_path, "r") as f:
            lines = f.read().splitlines()
    except OSError:
        return True
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "imsg-ssh-gate" in stripped and "--brain" not in stripped:
            return True
    return False


def _notice_unfenced_gate(cfg, io, st, mark_handle, now, log_path):
    gate_state = st.setdefault("gate_fence", {})
    last_iso = gate_state.get("last_notice_at")
    due = True
    if last_iso:
        try:
            due = now - schedule.parse_iso(last_iso) >= GATE_NOTICE_INTERVAL
        except Exception:
            due = True
    if due:
        _send_notice(io, cfg, mark_handle, GATE_NOTICE_TEXT, log_path)
        gate_state["last_notice_at"] = schedule.to_iso_utc(now)


def _run_failover(cfg, io, st, mode, lease, mark_handle, now, log_path):
    fst = st["failover"]
    backup = copy.deepcopy(fst)
    lease_ok = True

    try:
        if mode in ("auto", "mac"):
            akp = cfg.get("authorized_keys_path") or os.path.expanduser("~/.ssh/authorized_keys")
            if _gate_is_unfenced(akp):
                # Skip failover entirely this tick: do not call
                # failover.step, and leave st["failover"] untouched so a
                # paused run keeps its counters exactly as they were,
                # same as mode "off".
                _log(log_path, "unfenced_gate_line", "")
                _notice_unfenced_gate(cfg, io, st, mark_handle, now, log_path)
                return

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
            docker_ok = True
            if acts.docker == "up":
                docker_ok = io.docker_compose(cfg["docker"], cfg["repo_dir"], "up")
            elif acts.docker == "stop":
                io.docker_compose(cfg["docker"], cfg["repo_dir"], "stop")

            if acts.docker == "up" and not docker_ok:
                _send_notice(io, cfg, mark_handle, DOCKER_UP_FAILED_TEXT, log_path)
            else:
                for text in acts.notices:
                    _send_notice(io, cfg, mark_handle, text, log_path)
    finally:
        _save_state(cfg["state_path"], st)


def _recover_last_done(cfg, st, allow, now, log_path):
    """After a corrupt state file is recovered (moved aside, state reset
    to {}), seed last_done from the reminder files still on disk.

    Without this, a recurring reminder whose last-sent slot only lived in
    the lost state would look never-sent and fire again for every slot
    the lookback window still covers - possibly several repeats in one
    tick. Setting last_done to the latest due slot (the same slot the
    clock would itself pick next) makes that slot look already handled,
    so nothing already sent before the corruption is sent again; only
    slots after now are still eligible.
    """
    reminders_dir = cfg["reminders_dir"]
    if not os.path.isdir(reminders_dir):
        return
    last_done = st["clock"].setdefault("last_done", {})
    try:
        filenames = sorted(f for f in os.listdir(reminders_dir) if f.endswith(".json"))
    except OSError:
        return
    for filename in filenames:
        file_id = filename[:-len(".json")]
        path = os.path.join(reminders_dir, filename)
        try:
            with open(path, "rb") as f:
                raw = f.read()
            data = json.loads(raw.decode("utf-8"))
            rem = schedule.validate(data, allow=allow, file_id=file_id)
        except Exception:
            # An invalid file is the clock's problem to log and skip, not
            # this recovery step's; just leave it out of the seed.
            continue
        slot = schedule.due_slot(rem, now, None)
        if slot is not None:
            last_done[rem["id"]] = schedule.to_iso_utc(slot)


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
        st, recovered = _load_state(cfg["state_path"], log_path)
        st.setdefault("failover", {})
        st.setdefault("clock", {})

        try:
            env = _read_env(cfg["env_path"])
            allow = schedule.parse_allowlist(env.get("IMESSAGE_ALLOW_FROM", ""))
            mark_handle = env.get(cfg["mark_handle_env"]) or None
        except Exception as exc:
            # A malformed .env or allowlist must not stop failover from
            # running: fall back to "nobody allowed, no Mark handle" for
            # this tick rather than crashing before failover even starts.
            _log(log_path, "error", "env %s" % type(exc).__name__)
            allow = set()
            mark_handle = None

        if not mark_handle:
            _log(log_path, "config_missing", "mark_handle")

        if recovered:
            _recover_last_done(cfg, st, allow, now, log_path)

        mode = _senders.read_text(cfg["mode_path"], "off").strip()
        lease = _clean_lease(_senders.read_text(cfg["lease_path"], "pc"))

        try:
            _run_failover(cfg, io, st, mode, lease, mark_handle, now, log_path)
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
