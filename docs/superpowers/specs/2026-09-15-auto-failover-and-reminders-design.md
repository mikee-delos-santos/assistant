# Automatic failover and shared reminders - design

Date: 2026-09-15. Status: approved by Mark in chat (design and build in one go).
Related: ROADMAP.md "Proposal: automatic failover", "Handoff: Mac brain failover drill".

## 1. Goals

1. Exactly one brain (PC or Mac) talks on iMessage at any time, and the switch happens
   without a human.
2. Reminders survive a brain switch. Four kinds are needed:
   - fixed text at a time
   - recurring fixed text
   - smart jobs (the brain must think when the job fires)
   - reminders to other allowlisted family members (for example Kath)
3. A missed reminder is sent late, marked late, if it is less than 2 hours late.
   Older ones are skipped and reported to Mark once.
4. Small footprint on the MacBook Air: one short launchd job, no new always-on process.

Not goals: group chats, attachments, Apple Reminders app, running two voices on purpose.

## 2. Architecture

Everything that decides lives on the Mac, next to the iMessage gate. The Mac is the only
place iMessage exists, so it is the right place for the single source of truth.

```
Mac (always on)
+-----------------------------------------------------------------------------+
| launchd: com.assistant.brain-control   (every 30 s, one short Python run)   |
|   brain_control.py tick                                                     |
|     1. failover step   -> ~/.imsg-bridge/active-brain  (lease: pc | mac)    |
|                        -> docker compose up/stop (Mac brain)                |
|     2. reminder step   -> reads workspace/reminders/*.json (synced)         |
|                        -> text:  ssh 127.0.0.1 (clock key) -> gate --brain clock |
|                        -> smart: POST /hooks/agent on the lease holder      |
|   state: ~/.brain-control/state.json   (Mac only, never synced)             |
|                                                                             |
| imsg-ssh-gate --brain pc | mac | clock                                      |
|   pc/mac: watch notifications and send only if brain == lease               |
|   clock:  send only (no watch), same send guards as the brains              |
+-----------------------------------------------------------------------------+
        ^ ssh (pc key)                          ^ ssh (mac key)
   PC brain (OpenClaw)                     Mac brain (OpenClaw, container)
   `reminder` tool writes files            `reminder` tool writes files
        \______________ workspace/reminders/<id>.json (Syncthing) ______/
```

Units (each one file, testable alone):

| Unit | Where it runs | Job |
|---|---|---|
| `scripts/brain_control/schedule.py` | Mac + both brain images | Pure schedule math: parse and validate a reminder, find the due occurrence, late/skip decision. No I/O |
| `scripts/brain_control/failover.py` | Mac | State machine. Inputs: PC health, Syncthing completion, Mac brain running. Outputs: lease, docker action, notice |
| `scripts/brain_control/clock.py` | Mac | Reads reminder files and state, decides sends, calls the senders |
| `scripts/brain_control/senders.py` | Mac | Real I/O: gate subprocess send, `/hooks/agent` POST, docker, health, Syncthing API |
| `scripts/brain_control/main.py` | Mac | One tick: lock, load config and state, run failover then clock, save state |
| `scripts/reminder.py` (`reminder` in the image) | brains | CLI for Brice: `add`, `list`, `cancel` |
| `scripts/imsg-ssh-gate.py` | Mac | Gains `--brain` and lease fencing |

Python must run on Mac `/usr/bin/python3` (3.9) and in the image (3.11). Standard library only.

## 3. Failover

### 3.1 Lease

- File `~/.imsg-bridge/active-brain`, content `pc` or `mac` plus newline.
- Written atomically (temp file in the same folder, then `os.replace`).
- Missing or unreadable file means `pc` (today's behavior).
- Manual pin: `~/.brain-control/mode` with `auto`, `pc`, `mac`, or `off`. The default is
  `off` until Mark sets it to `auto` (ruling R12): failover must never start moving the
  lease and starting the Mac brain container on its own, before Mark has had a chance to
  check the config. `pc`/`mac` force the lease and the Mac brain state. `off` makes the
  tick do nothing for failover (reminders still run).

### 3.2 Health inputs

- PC brain healthy = `GET http://100.123.4.5:18789/healthz` returns HTTP 2xx within 5 s.
  (The PC publishes the gateway on the tailnet with `tailscale serve`.)
- PC Syncthing in sync = Syncthing REST on the Mac:
  `/rest/system/connections` shows the PC device connected, and
  `/rest/db/completion?folder=openclaw-workspace&device=<PC>` has `needItems == 0`.
- Mac brain running = `docker inspect -f '{{.State.Running}}' openclaw` is `true`.

### 3.3 State machine (mode `auto`)

Streak counters live in state.json. A health check that errors counts as a failure.

```
lease=pc:
  PC healthy                   -> fail_streak = 0
  PC unhealthy                 -> fail_streak += 1
  fail_streak >= 5 (~2.5 min)  -> FAILOVER: write lease=mac, then `docker compose up -d openclaw`,
                                  then notice to Mark "Brice moved to the Mac"
  Mac brain running and lease=pc for 2 ticks in a row -> `docker compose stop openclaw`
                                  (someone started it by hand while the PC is fine)

lease=mac:
  Mac brain not running        -> `docker compose up -d openclaw`
  PC healthy                   -> ok_streak += 1, else ok_streak = 0
  ok_streak >= 3 AND PC Syncthing in sync
                               -> FAIL BACK: write lease=pc, then `docker compose stop openclaw`,
                                  then notice "Brice is back on the PC"
  ok_streak >= 3 but not in sync for 20 ticks (10 min)
                               -> one notice "PC is up but memory is not synced. Log in on the PC."
                                  Keep lease=mac; the Mac brain keeps talking.
```

Order rules:
- Failover writes the lease before starting the Mac brain. A PC brain that comes back
  late is already fenced.
- Fail back writes the lease before stopping the Mac brain. There is never a moment
  with no voice, and the gate makes sure only one voice is heard.

Why 5 ticks at 30 s: short restarts of the PC container (about 30-60 s) do not cause a switch.

### 3.4 Gate fencing

- `authorized_keys` forced commands become `imsg-ssh-gate --brain pc` / `--brain mac`.
  A key line without `--brain` keeps today's behavior (no fencing), so rollout is safe.
- `--brain pc|mac` in rpc mode:
  - The connection, `chats.list`, `messages.history`, and `watch.subscribe` all still work.
    The brain's iMessage channel stays healthy, so it does not hit OpenClaw's restart limit.
  - Each incoming `message` notification is dropped unless brain == lease at that moment.
  - `send` is rejected with "not the active brain" unless brain == lease.
- `--brain clock`: rpc mode allows only `send` (no watch, no history, no chats).
  It keeps every existing send guard (1:1 only, the person must have texted the assistant).
- Any other `--brain` value: deny.
- The lease is read on every check (it is a tiny file). No caching.

Known window: two gate processes read the lease at slightly different moments during a
flip. A message that arrives in that same instant can reach both brains. Accepted.

Unfenced guard (ruling R13): a key line without `--brain` is unfenced by design for a
safe rollout, but it also means the gate cannot tell a pc/mac connection from the clock's
send-only one apart - failover must not run while that is true, or it could move the
lease to a brain the gate is not actually fencing. So the tick checks `authorized_keys`
itself before applying failover in mode `auto` or `mac`: if any non-comment line
mentions `imsg-ssh-gate` without `--brain`, failover is paused for that tick (no lease
move, no docker action, failover's own counters untouched) and Mark gets one notice
about it per 24 hours, asking him to add `--brain pc` / `--brain mac` to the gate lines.
A file that cannot be read is treated the same as an unfenced line (fail safe).

## 4. Reminders

### 4.1 File format (`workspace/reminders/<id>.json`)

One file per reminder. Only its creator writes it, and the clock only deletes it. So two
machines never edit the same file.

```json
{
  "version": 1,
  "id": "r-20260915T0930-3f9a",
  "kind": "text",
  "name": "Trash day",
  "to": ["+639xxxxxxxxx"],
  "text": "Trash day today!",
  "prompt": null,
  "schedule": {"type": "weekly", "days": ["mon"], "time": "08:00"},
  "tz": "Asia/Manila",
  "late_limit_minutes": 120,
  "created_at": "2026-09-15T01:30:00Z",
  "created_by": "brice"
}
```

- `id`: `r-` + creation time + 4 random hex. Must match `^r-[0-9A-Za-z-]{1,60}$` and the file name.
- `kind`: `text` (needs `text`, 1-1000 chars) or `smart` (needs `prompt`, 1-2000 chars).
- `to`: 1-5 handles for `text`; exactly 1 for `smart`. Each must be in the allowlist.
- `schedule.type`:
  - `once`: `at` = ISO 8601 with offset.
  - `daily`: `time` = `HH:MM`.
  - `weekly`: `days` = non-empty subset of `mon..sun`, `time` = `HH:MM`.
- `tz`: IANA name, default `Asia/Manila`.
- `late_limit_minutes`: 0-1440, default 120.
- Unknown keys are an error (strict), so typos do not silently change behavior.

### 4.2 `reminder` tool (in the brain image)

```
reminder add-text  --to <handle> [--to ...] --text "<text>" --name "<name>" <schedule>
reminder add-smart --to <handle> --prompt "<prompt>" --name "<name>" <schedule>
   <schedule> = --at <ISO with offset> | --daily HH:MM | --weekly mon,thu HH:MM   [--tz Asia/Manila]
reminder list            one JSON line per reminder, with next_run in Manila time
reminder cancel <id>     deletes the file
```

- Output is one JSON line: `{"ok": true, ...}` or `{"ok": false, "error": "..."}`.
- The allowlist comes from `IMESSAGE_ALLOW_FROM` in the container env.
- A write goes to `/home/node/.openclaw/tmp/` first, then `os.replace` into
  `workspace/reminders/`. A half-written file is never visible to Syncthing.
- Limits: at most 100 reminder files. A `once` reminder in the past is refused.
- Uses the same `schedule.py` validation as the clock.

### 4.3 Clock step (each tick)

For each valid file:
1. Find the latest occurrence `slot` with `slot <= now`, `slot > created_at`,
   and `slot > last_done[id]` (from state.json).
2. No such slot -> nothing to do.
3. `now - slot > late_limit` -> mark done as `skipped`, add to the skipped report.
4. Otherwise send:
   - `text`: for each recipient, `ssh` to `mikee@127.0.0.1` with the clock key
     (`~/.brain-control/clock_ed25519`), command `/opt/homebrew/bin/imsg rpc`. The key's
     `authorized_keys` line is `from="127.0.0.1,::1",restrict,command="<gate> --brain clock"`.
     Write one JSON-RPC `send` request (`chat_identifier` = handle, `text`), read one response.
     Why SSH and not a direct subprocess: only `sshd` has Full Disk Access (chat.db) and the
     Messages Automation permission today. A launchd Python process would need new TCC grants. If more than
     2 minutes late, the text starts with `(late) `.

     The send call returns one of three outcomes, never a plain success/failure guess
     (ruling R10): `"ok"` (a matching response with a result and no error), `"retry"`
     (the gate's error says `retry_safe: true`, or the ssh connection failed before any
     byte came back at all), or `"final"` (every other failure - a plain error, a gate
     rejection, or a timeout/EOF once some output had already started, since the send may
     already be in flight by then). `"retry"` gets the usual per-recipient backoff and
     6-attempt cap. `"final"` stops retrying that recipient right away: it counts as done
     for completion purposes and the reminder's name goes on the Failed list this tick.
     An outcome that is genuinely unknown is never treated as either success or a safe
     retry.
   - `smart`: `POST <lease holder>/hooks/agent` with `message` = the prompt plus a short
     header (job name, scheduled time, "send the result to <handle> on iMessage"),
     `name` = the reminder name, `deliver: true`, `channel: "imessage"`, `to` = the handle,
     `idempotencyKey` = `<id>:<slot ISO>`. PC URL `http://100.123.4.5:18789`, Mac URL
     `http://127.0.0.1:18789`. Header `Authorization: Bearer <hooks token>`.
5. Success -> `last_done[id] = slot`. For `once`, delete the file.
6. Failure -> keep it; the next tick retries until the late limit is passed.
   Per-recipient partial success is recorded so a retry does not resend to people who got it.
7. Invalid file -> log once per file content hash; never send. A file newly logged as
   invalid this tick (ruling R11) is also listed in the tick's report to Mark, by file
   name, so a bad reminder file does not go unnoticed.

Safety limits in the clock (protect against a runaway brain writing many reminders):
- At most 10 sends per tick, at most 60 sends per day in total.
- At most one report text to Mark per tick, not one per category: the Skipped, Failed,
  and Invalid lines (whichever are non-empty) are joined into a single message.
- A time budget (default 90s) on how long one tick's send loop may run: once it is used
  up, no new sends are started - whatever reminders are left over are picked up on the
  next tick. Notices (Skipped/Failed/Invalid) are still sent for what was already
  processed.
- After every send attempt, the tick's state is checkpointed to disk, so a crash
  mid-tick loses at most the attempt in progress, never an earlier one.

State file `~/.brain-control/state.json` (Mac only):
`{"lease_streaks": {...}, "last_done": {"<id>": "<slot ISO>"}, "partial": {...},
"sent_today": {"date": "...", "count": n}, "invalid_seen": {...}, "notices": {...}}`.
Entries for deleted reminder files are removed after 7 days.

### 4.4 Brain configuration (both hosts)

- `hooks.enabled=true`, `hooks.path=/hooks`, `hooks.token=${OPENCLAW_HOOKS_TOKEN}`,
  `hooks.allowedAgentIds=["main"]`, `hooks.allowRequestSessionKey=false`.
- The same hooks token on the PC, the Mac brain, and `~/.brain-control/hooks-token` (600).
  It is different from the gateway token.
- `docker-compose.yml`: `mem_limit: ${OPENCLAW_MEM_LIMIT:-3g}` so the Mac brain cannot starve
  the rest of the Docker VM.
- TOOLS.md and a `reminders` skill tell Brice to use `reminder` and never the built-in
  `cron` tool for reminders.

### 4.5 Migration

- `memory/tasks.json` "Buy flowers" is past and stopped: delete that entry now.
- PC OpenClaw cron jobs (only readable when the PC is on): list them, recreate each as a
  `smart` reminder, then `openclaw cron rm` each one. Record the list (names only) in ROADMAP.

## 5. Error handling

| Failure | Behavior |
|---|---|
| Tick crashes | launchd starts the next tick in 30 s. State is saved only at the end of a successful step, atomically |
| Two ticks overlap | `fcntl.flock` on `~/.brain-control/tick.lock`; the second tick exits at once |
| Docker not running | failover step logs and retries; lease is still correct |
| Syncthing API down | treated as "not in sync"; no fail back |
| Gate send fails | retry next tick until the late limit |
| Hook POST fails (brain restarting) | retry next tick until the late limit |
| state.json corrupt | move it aside as `state.json.bad-<time>`, start fresh; `created_at` stops old slots from refiring |
| System time jumps (NTP) | slots are computed from wall time each tick; `last_done` stops refiring |

Log: `~/.brain-control/brain-control.log`, one line per event, never message text or handles.

## 6. Testing

- Unit tests with `unittest`, runnable on the Mac: `python3 -m unittest discover scripts/tests`.
  - `schedule.py`: validation, DST-free Manila times, weekly day matching, once, late and skip.
  - `failover.py`: every transition in 3.3 with fake inputs, including manual mode.
  - `clock.py`: fake senders; partial success, retries, limits, once deletion.
  - gate: `--brain` parsing, notification drop and send reject by lease, clock mode allowlist.
    Uses the existing gate functions with a fake lease path.
  - `reminder.py`: argument parsing, allowlist, atomic write.
- Live drill on the Mac after install:
  1. Text reminder to Mark 2 minutes ahead; arrives once.
  2. Smart reminder to Mark; arrives once with a thought-out answer.
  3. Failover: PC off -> lease flips to mac after about 2.5 min, Mac brain starts, text works.
  4. Fail back: PC on and logged in -> lease flips to pc after sync, Mac brain stops.

## 7. Rollout order

1. Code, tests, reviews, PR.
2. Install on the Mac: gate (backward compatible), brain-control with mode `off`.
3. Mark edits `authorized_keys`: add `--brain pc` / `--brain mac` to the brain lines and add the
   clock key line (the tool cannot edit that file).
4. Configure hooks and memory limit on the Mac brain; PC Claude does the PC side.
5. Set mode `auto`. Run the drill.
6. Migrate PC cron reminders when the PC is on.
