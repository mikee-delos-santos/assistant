"""Real I/O for the brain-control tick: HTTP, docker, ssh, and local files.

Everything in this module talks to something outside the process: an HTTP
endpoint, a subprocess, or a file on disk. The pure failover and clock
logic never calls these directly; main.py wires them in through the `io`
object so tests can swap in fakes. Nothing here ever logs a secret
(API keys, ssh keys, the hooks token) or message text.
"""

import json
import os
import re
import select
import subprocess
import tempfile
import time
import urllib.request
from typing import Optional


def http_ok(url, timeout=5.0, headers=None, body=None):
    # type: (str, float, Optional[dict], Optional[dict]) -> bool
    """GET, or POST JSON when `body` is given. True on any 2xx response."""
    try:
        req_headers = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, headers=req_headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def pc_healthy(url):
    # type: (str) -> bool
    return http_ok(url, 5)


def syncthing_in_sync(config_xml, folder, device_name):
    # type: (str, str, str) -> bool
    """Whether the named Syncthing device is connected and fully synced.

    Reads the API key out of the local config.xml, then asks the local
    Syncthing REST API for the device list, the connection state, and the
    folder completion. Any failure (missing file, bad XML, network error,
    device not found) reads as "not in sync" rather than raising.
    """
    try:
        with open(config_xml, "r") as f:
            xml = f.read()
        match = re.search(r"<apikey>([^<]*)</apikey>", xml)
        if not match:
            return False
        api_key = match.group(1)
        headers = {"X-API-Key": api_key}

        devices = _syncthing_get(headers, "http://127.0.0.1:8384/rest/config/devices")
        device_id = None
        for dev in devices:
            if dev.get("name") == device_name:
                device_id = dev.get("deviceID")
                break
        if not device_id:
            return False

        connections = _syncthing_get(headers, "http://127.0.0.1:8384/rest/system/connections")
        conn = connections.get("connections", {}).get(device_id)
        if not conn or not conn.get("connected"):
            return False

        completion = _syncthing_get(
            headers,
            "http://127.0.0.1:8384/rest/db/completion?device=%s&folder=%s" % (device_id, folder),
        )
        return completion.get("needItems") == 0
    except Exception:
        return False


def _syncthing_get(headers, url):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def docker_running(docker, name):
    # type: (str, str) -> bool
    try:
        out = subprocess.check_output(
            [docker, "inspect", "-f", "{{.State.Running}}", name],
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return out.decode("utf-8").strip() == "true"
    except Exception:
        return False


def docker_compose(docker, repo_dir, action):
    # type: (str, str, str) -> bool
    if action == "up":
        args = [docker, "compose", "up", "-d", "openclaw"]
    elif action == "stop":
        args = [docker, "compose", "stop", "openclaw"]
    else:
        return False
    try:
        subprocess.check_call(
            args, cwd=repo_dir, timeout=180,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def read_text(path, default):
    # type: (str, str) -> str
    try:
        with open(path, "r") as f:
            return f.read()
    except (FileNotFoundError, IsADirectoryError):
        return default


def write_atomic(path, data, mode=0o600):
    # type: (str, str, int) -> None
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def gate_send(ssh_key, known_hosts, target, handle, text, timeout=60):
    # type: (str, str, str, str, str, float) -> bool
    """Send one iMessage through the clock-fenced ssh gate.

    Speaks one JSON-RPC "send" request over ssh to the gate's clock role
    and waits for a matching response. Any error, timeout, or malformed
    response reads as failure; it never raises.

    Waiting for that response never blocks past `timeout`: a stalled ssh
    connection or a gate that never answers must not hang the tick, since
    the tick holds a flock and a hung tick blocks every later tick too.
    select() is used on the pipe's raw fd (not the buffered file object)
    so a byte that already arrived is never missed just because select
    was not asked about it again.
    """
    cmd = [
        "ssh", "-T", "-i", ssh_key,
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=2",
        "-o", "UserKnownHostsFile=%s" % known_hosts,
        "-o", "StrictHostKeyChecking=yes",
        target,
        "/opt/homebrew/bin/imsg rpc",
    ]
    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "send",
        "params": {"chat_identifier": handle, "text": text},
    }) + "\n"

    proc = None
    ok = False
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        proc.stdin.write(request.encode("utf-8"))
        proc.stdin.flush()

        fd = proc.stdout.fileno()
        buf = b""
        deadline = time.time() + timeout
        while True:
            newline_at = buf.find(b"\n")
            if newline_at == -1:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                ready, _, _ = select.select([fd], [], [], remaining)
                if not ready:
                    break  # timed out waiting for the next byte
                chunk = os.read(fd, 4096)
                if not chunk:
                    break  # gate closed the connection without answering
                buf += chunk
                continue
            line, buf = buf[:newline_at], buf[newline_at + 1:]
            try:
                msg = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if msg.get("id") == 1:
                ok = "result" in msg and "error" not in msg
                break
    except Exception:
        ok = False
    finally:
        if proc is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            if proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            try:
                proc.stdout.close()
            except Exception:
                pass
    return ok


def hook_agent(base_url, token, payload):
    # type: (str, str, dict) -> bool
    url = base_url.rstrip("/") + "/hooks/agent"
    headers = {"Authorization": "Bearer %s" % token}
    return http_ok(url, timeout=20, headers=headers, body=payload)
