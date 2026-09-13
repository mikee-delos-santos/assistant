#!/usr/bin/python3
"""SSH forced command for the brain's "launch" key. Runs on the Mac.

It does exactly one thing: open a visible Warp window running `claude` in one
allowlisted project, so Mark can drive that session from the Claude app (Remote Control
starts on its own because `remoteControlAtStartup` is set in the Claude settings).

Accepted commands (nothing else, no shell, no free text):
  list                 print the allowed project keys as JSON
  launch <project>     open that project's session

Projects live in a private map on the Mac, ~/.claude-launch/projects.json (not in git):
  {"projects": {"<key>": {"path": "/Users/mikee/workspace/<dir>",
                          "config_dir": "/Users/mikee/.claude"}}}
The corporate project's real folder name stays in that private file only.
"""
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.parse

HOME = os.path.expanduser("~")
BASE = os.path.join(HOME, ".claude-launch")
MAP = os.path.join(BASE, "projects.json")
LOG = os.path.join(BASE, "launch.log")
STATE = os.path.join(BASE, "last-launch.json")
LOCK = os.path.join(BASE, "launch.lock")
DEFAULT_CONFIG_DIR = os.path.join(HOME, ".claude")
WORKSPACE = os.path.join(HOME, "workspace")
CONFIG_DIRS = {os.path.join(HOME, ".claude"), os.path.join(HOME, ".claude-corporate")}
WARP_CONFIGS = os.path.join(HOME, ".warp", "launch_configurations")
KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MIN_SECONDS_BETWEEN_LAUNCHES = 60      # same project
MIN_SECONDS_BETWEEN_ANY_LAUNCH = 5     # any project (Mark: sessions may be opened one after another)
MAX_LAUNCHES_PER_DAY = 10
MAX_LOG_BYTES = 1024 * 1024


def log(event, detail):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > MAX_LOG_BYTES:
            return
        with open(LOG, "a") as fh:
            fh.write("%s %s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), event, detail))
    except OSError:
        pass


def reply(payload, code=0):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.exit(code)


def deny(reason):
    log("deny", reason)
    reply({"ok": False, "error": reason}, 126)


def load_projects():
    try:
        with open(MAP) as fh:
            projects = json.load(fh)["projects"]
    except (OSError, ValueError, KeyError, TypeError) as err:
        deny("project map unusable: %s" % type(err).__name__)
    clean = {}
    for key, entry in projects.items():
        if not KEY_PATTERN.fullmatch(str(key)) or not isinstance(entry, dict):
            continue
        if not str(entry.get("path", "")).isascii():
            continue
        path = os.path.realpath(str(entry.get("path", "")))
        config_dir = os.path.realpath(str(entry.get("config_dir", "")))
        # A project must be a real folder directly or deeper under ~/workspace, and use a
        # known Claude config folder.
        if not path.startswith(WORKSPACE + os.sep) or not os.path.isdir(path):
            continue
        if config_dir not in CONFIG_DIRS:
            continue
        clean[key] = {"path": path, "config_dir": config_dir}
    return clean


def launch_allowed(key, now):
    """Check the limits. Call with the lock held. Returns an error text or None."""
    state = read_state()
    last = state.get("last", {})
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    if now - last.get(key, 0) < MIN_SECONDS_BETWEEN_LAUNCHES:
        return "project %s was launched less than %ds ago" % (key, MIN_SECONDS_BETWEEN_LAUNCHES)
    if now - max(last.values() or [0]) < MIN_SECONDS_BETWEEN_ANY_LAUNCH:
        return "a session was launched less than %ds ago" % MIN_SECONDS_BETWEEN_ANY_LAUNCH
    if state.get("day") == day and state.get("count", 0) >= MAX_LAUNCHES_PER_DAY:
        return "daily limit of %d launches reached" % MAX_LAUNCHES_PER_DAY
    return None


def read_state():
    try:
        with open(STATE) as fh:
            state = json.load(fh)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def record_launch(key, now):
    state = read_state()
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    last = state.get("last", {})
    last[key] = now
    count = state.get("count", 0) if state.get("day") == day else 0
    state = {"last": last, "day": day, "count": count + 1}
    with open(STATE, "w") as fh:
        json.dump(state, fh)


def warp_config(key, project):
    """Write the Warp launch configuration for a project and return its file name."""
    name = "brice-%s" % key
    if project["config_dir"] == DEFAULT_CONFIG_DIR:
        # The default Claude state is ~/.claude.json + ~/.claude. Setting CLAUDE_CONFIG_DIR
        # to ~/.claude would move the state file and show login/trust prompts instead.
        command = "env -u CLAUDE_CONFIG_DIR command claude"
    else:
        command = "CLAUDE_CONFIG_DIR=%s command claude" % shlex.quote(project["config_dir"])
    # json.dumps gives double-quoted strings, which YAML reads as plain strings.
    body = "\n".join([
        "name: %s" % json.dumps(name, ensure_ascii=False),
        "windows:",
        "  - tabs:",
        "      - title: %s" % json.dumps("Claude: %s" % key, ensure_ascii=False),
        "        layout:",
        "          cwd: %s" % json.dumps(project["path"], ensure_ascii=False),
        "          commands:",
        "            - exec: %s" % json.dumps(command, ensure_ascii=False),
        "",
    ])
    os.makedirs(WARP_CONFIGS, exist_ok=True)
    file_name = name + ".yaml"
    with open(os.path.join(WARP_CONFIGS, file_name), "w") as fh:
        fh.write(body)
    return file_name


def main():
    words = os.environ.get("SSH_ORIGINAL_COMMAND", "").split()
    projects = load_projects()
    if words == ["list"]:
        log("list", "%d projects" % len(projects))
        reply({"ok": True, "projects": sorted(projects)})
    if len(words) != 2 or words[0] != "launch":
        deny("expected 'list' or 'launch <project>'")
    key = words[1]
    if not KEY_PATTERN.fullmatch(key) or key not in projects:
        deny("unknown project")
    os.makedirs(BASE, exist_ok=True)
    with open(LOCK, "w") as lock:
        # One launch decision at a time, so two connections cannot both pass the limits.
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = time.time()
        problem = launch_allowed(key, now)
        if problem:
            deny(problem)
        file_name = warp_config(key, projects[key])
        url = "warp://launch/" + urllib.parse.quote(file_name)
        try:
            done = subprocess.run(["/usr/bin/open", url], capture_output=True, timeout=20)
            opened = done.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            opened = False
        if not opened:
            log("launch-failed", key)
            reply({"ok": False, "error": "could not hand the launch to Warp"}, 1)
        record_launch(key, now)
    log("launch", key)
    # `open` only hands the URL to Warp. A locked screen or a Claude prompt can still stop
    # the session, so do not claim it is ready.
    reply({"ok": True, "project": key,
           "note": "launch requested; the session appears in the Claude app once it starts"})

if __name__ == "__main__":
    main()
