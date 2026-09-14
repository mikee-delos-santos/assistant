"""Failover decision logic for the iMessage brain lease.

Pure state machine: given the current tick's inputs and the persisted
counters, decide whether the lease should move and whether the Mac brain
container should start or stop. No I/O happens here; a later module reads
health checks, calls docker, and persists state.json.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

FAIL_TICKS = 5
OK_TICKS = 3
STRAY_TICKS = 2
UNSYNCED_NOTICE_TICKS = 20
MODES = ("auto", "pc", "mac", "off")


@dataclass
class Inputs:
    mode: str
    lease: str
    pc_healthy: bool
    pc_in_sync: bool
    mac_running: bool


@dataclass
class Actions:
    lease: Optional[str] = None
    docker: Optional[str] = None
    notices: List[str] = field(default_factory=list)


def _reset_streaks(st):
    st["fail_streak"] = 0
    st["ok_streak"] = 0
    st["stray_ticks"] = 0
    st["unsynced_ticks"] = 0
    st["unsynced_noticed"] = False


def _ensure(st):
    st.setdefault("fail_streak", 0)
    st.setdefault("ok_streak", 0)
    st.setdefault("stray_ticks", 0)
    st.setdefault("unsynced_ticks", 0)
    st.setdefault("unsynced_noticed", False)


def step(inp, st):
    # type: (Inputs, Dict) -> Actions

    # Mode off, or an unrecognized mode: leave st untouched so a paused
    # run keeps its counters exactly as they were.
    if inp.mode not in MODES or inp.mode == "off":
        return Actions()

    if inp.mode == "pc":
        actions = Actions()
        if inp.lease != "pc":
            actions.lease = "pc"
        if inp.mac_running:
            actions.docker = "stop"
        _reset_streaks(st)
        return actions

    if inp.mode == "mac":
        actions = Actions()
        if inp.lease != "mac":
            actions.lease = "mac"
        if not inp.mac_running:
            actions.docker = "up"
        _reset_streaks(st)
        return actions

    # mode == "auto"
    _ensure(st)
    actions = Actions()

    if inp.lease == "mac":
        if not inp.mac_running:
            actions.docker = "up"

        if inp.pc_healthy:
            st["ok_streak"] += 1
        else:
            # PC dropped again mid-recovery: the unsynced notice no longer
            # applies, and it should be free to fire again next time.
            st["ok_streak"] = 0
            st["unsynced_ticks"] = 0
            st["unsynced_noticed"] = False

        if st["ok_streak"] >= OK_TICKS:
            if inp.pc_in_sync:
                actions.lease = "pc"
                actions.docker = "stop"
                actions.notices = ["Brice is back on the PC."]
                st["ok_streak"] = 0
                st["unsynced_ticks"] = 0
                st["unsynced_noticed"] = False
            else:
                st["unsynced_ticks"] += 1
                if st["unsynced_ticks"] >= UNSYNCED_NOTICE_TICKS and not st["unsynced_noticed"]:
                    actions.notices = [
                        "PC brain is up but memory is not synced yet. "
                        "Log in on the PC so Syncthing starts."
                    ]
                    st["unsynced_noticed"] = True
    else:
        # Treat any lease value other than "mac" as the PC holding it.
        if inp.mac_running:
            st["stray_ticks"] += 1
        else:
            st["stray_ticks"] = 0

        if st["stray_ticks"] >= STRAY_TICKS:
            actions.docker = "stop"
            st["stray_ticks"] = 0

        if inp.pc_healthy:
            st["fail_streak"] = 0
        else:
            st["fail_streak"] += 1
            if st["fail_streak"] >= FAIL_TICKS:
                actions.lease = "mac"
                actions.docker = "up"
                actions.notices = ["Brice moved to the Mac (PC brain not reachable)."]
                st["fail_streak"] = 0

    return actions
