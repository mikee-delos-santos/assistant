# Assistant - Roadmap & Status (source of truth)

This file is the coordination hub for the project. Track work here, not in Jira.
(The personal Jira AS board is linked to Mindr and is intentionally left untouched;
the AS-xx numbers below are kept only as historical labels.)

Coordination model: this file + git branches + PRs on
https://github.com/mikee-delos-santos/assistant. Update this file at the end of a
work session. One branch per task, PR to merge.

Status legend: DONE | WIP (in progress) | TODO | DEFERRED

## Where things stand right now
- The brain is LIVE on the Windows PC: OpenClaw in Docker, healthy, default model
  Claude Sonnet 4.6, auto-restarts on boot, spend-capped Anthropic API key.
- Reachable on the PC now: `docker exec -it openclaw openclaw chat`.
- Phone access is published over Tailscale (tailnet-only):
  http://desktop-3p37btg.taila8a422.ts.net:18789/ - iPhone device pairing still to approve.
- Mac onboarding is mostly done (2026-09-13): Tailscale, Docker Desktop, imsg, and
  Syncthing are installed. Messages is signed in, Full Disk Access and Remote Login
  are on. The Mac .env has the same secrets as the PC (sent over Taildrop, never
  pasted in chat). Syncthing mirrors the memory folder PC <-> Mac over the tailnet.
  The Mac container stays STOPPED while the PC is the active brain. Failover to the Mac
  brain was tested for real on 2026-09-15: see "Handoff: Mac brain failover drill".
- iMessage family channel is LIVE (2026-09-13 18:32): Mark texted the assistant number
  from his iPhone and the PC brain replied through the Mac. See "Go-live result" below.
- iMessage identity is now OPTION B (2026-09-13): Messages on the Mac is signed in to
  a dedicated Apple ID for the assistant, with its own phone number. The Mac's macOS
  Apple Account is still Mark's. A test from Mark's iPhone reached the assistant number.
  The handles are private: see "Option B: identity switch" below.
- Assistant name / persona: NOT chosen yet (it becomes the iMessage contact name).
- What to do next: see "Next steps" just below.

## Next steps (updated 2026-09-13, after iMessage go-live)
Read this first. PC Claude: `git pull` before acting, and before editing this file.
Each row names who does it. "Mark" rows are decisions or phone/GUI actions.

Do now
| # | Who | Task | Notes |
|---|---|---|---|
| N1 | Mark | Do NOT install the pending macOS update on the Mac yet | Updates can reset Full Disk Access + Automation and break the bridge. After updating, ask Mac Claude to re-check permissions and run a text test |

Soon - make the assistant yours
| # | Who | Task | Notes |
|---|---|---|---|
| N2 | Mark + PC | First-run chat to set identity: `docker exec -it openclaw openclaw chat`, follow `BOOTSTRAP.md` | Fills `IDENTITY.md` (name, vibe), `SOUL.md` (values, Boundaries), `USER.md` (Mark + family). Files live in `data/openclaw/workspace` (synced to the Mac, NOT in git). No secrets in them |
| N3 | Mark | Decide red lines; mark each HARD or SOFT | SOFT = written in `AGENTS.md` Red Lines / `SOUL.md` Boundaries (the model follows them but can be tricked). HARD = enforced in code: PC `openclaw.json` (allowFrom, dmPolicy) or the Mac gate. Send the HARD list to Mac Claude / PC Claude |
| N4 | Mark | Save the assistant number as a contact (the name from N2) on Mark's and his wife's phones | |
| N5 | Wife (optional) | Wife texts the assistant number; expect a reply | Her handle is already in allowFrom. Option B step 7 |

Now (2026-09-14)
| # | Who | Task | Notes |
|---|---|---|---|
| N8 | Mark + PC | SMS failsafe: SMS2 (allowFrom format check) and SMS5 if needed | Gate change live; SMS test passed on the Mac side 2026-09-14 |
| N9 | Mark + PC | Model fallbacks (M1-M7) | M0 approved 2026-09-14; M3 (OpenAI API key) is with Mark; M1/M2 can start now |

PC Claude cleanups
| # | Who | Task | Notes |
|---|---|---|---|
| N6 | PC | `git pull`; turn off threaded replies in OpenClaw's iMessage channel config | The Mac gate strips `reply_to` today (no imsg bridge on this Mac). Check the exact key in OpenClaw docs/config; restart; Mark texts once to confirm replies still work. Record the key here |
| N7 | PC | Update the old Option A / Phase B notes if anything still says "Option A" is current | Option B is current |

Later
| # | Who | Task | Notes |
|---|---|---|---|
| L1 | Mac + PC | Failover drill (Mac brain) | Failover half DONE 2026-09-15 (iMessage reply from the Mac brain). Fail back is in progress: see "Handoff: Mac brain failover drill" |
| L2 | Mac + PC | Syncthing: verify live updates both ways and restart after a reboot | Only the first sync (25/25 files) is verified |
| L3 | Mac + PC | Exclude `.git` from the synced workspace (`.stignore` on BOTH hosts) | A failover mid-sync could break OpenClaw's git index |
| L4 | Mark | Encrypted backup of the workspace; FileVault on the Mac | Memory will hold family data |
| L5 | Mark | Consider making the GitHub repo private | It holds tailnet names and IPs (no secrets, no handles) |
| L6 | PC | Memory read/write test; approve iPhone pairing to the PC web UI; mobile-data (CGNAT) check | Old Phase 0/1 leftovers |
| L7 | Mac | Group chats and attachments | Both are denied by the gate today. Needs a design before enabling |

Done today (for context): Mac onboarded; Syncthing linked; PC runs imsg over SSH
through the Mac gate; Option B identity live; gate hides Mark's old history; SMS
forwarding to the Mac is effectively off (the iPhone no longer lists the Mac, and no
SMS rows arrived since the switch); end-to-end reply confirmed from the assistant number.

## Handoff: Mac brain failover drill (2026-09-15)

Mark turned the PC off on purpose. Mac Claude built the Mac brain and made it the active
brain. PC Claude: `git pull` first, then do the "Fail back" rows below.

Result: failover WORKS. Mark texted Brice and got a reply from the Mac brain
(gate.log `direct-send ok` 05:12:02). Brice read the synced memory (persona, USER.md,
recent notes). A one-shot `openclaw agent` reply took about 30s including CLI start.

What Mac Claude built on the Mac:
- Image `assistant/openclaw:with-ssh` built natively (the base digest has linux/arm64).
- Named volumes `openclaw_imsg_ssh` (key `mac-brain-imsg`) and `openclaw_launch_ssh`
  (key `mac-brain-launch`). Private keys were made inside the volumes (600, uid 1000).
  known_hosts entry is `host.docker.internal` with the Mac host key SHA256:EYJ... (checked).
- `authorized_keys` on the Mac (added by Mark): `from="127.0.0.1,::1",restrict,command=<gate>`.
  Docker Desktop on macOS proxies container traffic to the host, so sshd sees 127.0.0.1.
  Verified: `imsg-over-ssh status` from the container = exit 0.
- `openclaw onboard --non-interactive` (mode local, bind lan, token and API key as env
  refs, `--skip-bootstrap` so the synced workspace was not touched). Then set:
  model primary `anthropic/claude-sonnet-4-6`, `mcp.servers.chore-app`,
  `channels.imessage` enabled + `dmPolicy=allowlist` + allowFrom (3 handles, same count as
  the PC) + `cliPath=/usr/local/bin/imsg-over-ssh`. Channel status: running.
- Mac `.env` gained `IMSG_SSH_*`, `LAUNCH_SSH_*` (target `mikee@host.docker.internal`),
  and `BRAIN_HOST=mac`.

Found during the drill:
- Brice said "I'm on the PC (WSL)". The synced files said "this machine (WSL/PC)", and the
  container cannot tell the hosts apart. Fix: `BRAIN_HOST` (per-host `.env`, unset = pc) and
  `claude-launch where`. TOOLS.md has a "Where you run" section that tells Brice to check it.
  USER.md and CLAUDE-SESSIONS.md now name the PC and the Mac instead of "this machine".
  USER.md also said Mindr is on the PC; it is on the Mac.
- `claude-launch infopathy` on the Mac brain used to drop a trigger no one reads and report
  success. The wrapper now refuses it when `BRAIN_HOST=mac`. Missing launch key = clear
  JSON error instead of a shell error.
- NOT synced, by design, so a failover does not carry them: `openclaw.json`, `.env`,
  SSH keys, cron jobs (reminders set on the PC do NOT fire from the Mac), chat sessions,
  the SQLite index.
- Mac `.env` has an EMPTY `CHORES_MCP_TOKEN` (the PC got the token after the Mac `.env`
  was copied). Chores tools do not work on the Mac brain until it is sent over Taildrop.
- `send-rich` denied once at channel start, same as the PC (OpenClaw falls back to `send`).

Fail back (order matters: never two brains at once, and never a brain on stale memory)
| # | Who | Step | Status |
|---|---|---|---|
| F1 | Mark (Mac) | Add the `mac-brain-launch` line by hand: `from="127.0.0.1,::1",restrict,command="/Users/mikee/.claude-launch/claude-launch-gate" ssh-ed25519 <mac-brain-launch public key> mac-brain-launch`. Do NOT use `scripts/install-launch-key.sh`: it requires the comment `brice-launch`, hard-codes the PC IP, and deletes every ` brice-launch` line (the PC's launch key). Mac Claude then tests `claude-launch list` from the Mac brain | TODO |
| F2 | Mac | `docker compose stop openclaw` on the Mac; confirm it is stopped. Only then tell Mark to turn on the PC | TODO |
| F3 | Mark | Turn the PC on AND log in right away. The PC brain auto-starts as soon as Docker Desktop starts (`restart: unless-stopped`). PC Syncthing starts at login. Not checked: whether Docker Desktop on the PC starts at boot or at login. Either way the two race | TODO |
| F4 | PC | Right after login: `docker compose stop openclaw`, so the PC brain does not answer or write memory on stale files | TODO |
| F5 | PC | Wait until Syncthing shows the workspace folder "Up to Date" with the Mac. Check there are no `*sync-conflict*` files. The Mac changed USER.md, TOOLS.md, CLAUDE-SESSIONS.md, and the launch skill. If a conflict file exists, stop and tell Mark | TODO |
| F6 | PC | `git pull`; add `BRAIN_HOST=pc` to the PC `.env`; `docker compose up -d --build --force-recreate openclaw` (new wrapper in the image) | TODO |
| F7 | PC | `docker exec openclaw claude-launch where` = `pc`; `docker exec openclaw claude-launch list` still works with the PC key | TODO |
| F8 | Mark | Text Brice "where are you running?"; expect PC | TODO |
| F9 | PC | Taildrop `CHORES_MCP_TOKEN` to the Mac (an env line in a file, delete the copy after) | TODO |
| F10 | PC | Turn on Syncthing Staggered File Versioning for folder `openclaw-workspace` (GUI: Edit folder > File Versioning > Staggered, Maximum Age 365 days). Set the Versions Path OUTSIDE the workspace: `<PC repo>\\data\\stversions-openclaw-workspace` (create it first). Reason: the default `.stversions` sits inside the workspace, and OpenClaw could index old memory copies as current. The Mac is already set (2026-09-15, path `data/stversions-openclaw-workspace` in the Mac repo) | TODO |

Known gap: between Docker Desktop starting (F3) and F4, the PC brain runs on the old files. A text in that
window can get a stale answer or create a conflict file. Keep the window short.

Open decision for Mark: automatic failover (see "Proposal: automatic failover" below).

## Proposal: automatic failover (2026-09-15, not decided)

Today failover is manual. The danger of automating it is split brain: two brains watch the
same iMessage account, both reply to every text, and both write memory.

Key fact: every brain reaches iMessage through the gate on the Mac. So the Mac can decide
who is allowed to talk. No second brain can talk around it.

Design (all on the Mac):
1. Watchdog: a launchd job on the Mac runs every 60s.
2. Lease file: `~/.imsg-bridge/active-brain` holds `pc` or `mac`. Only the watchdog writes it.
3. Fencing in the gate: each brain key's forced command gets `--brain pc` or `--brain mac`.
   The gate denies `watch.subscribe` and `send` to the brain that does not hold the lease.
   A brain without the lease is deaf and mute, even if it is running.
4. State machine:

```
            PC healthy 3 checks in a row
            AND Syncthing says the PC needs 0 items
     +------------------------------------------------+
     |                                                |
     v                                                |
 [PC_ACTIVE]                                     [MAC_ACTIVE]
 lease=pc                                        lease=mac
 Mac brain stopped                               Mac brain running
     |                                                ^
     |  PC brain unhealthy 5 checks in a row (~5 min) |
     +------------------------------------------------+
        watchdog: lease=mac, then start Mac brain

 Fail back order: stop Mac brain -> wait for Syncthing -> lease=pc
```

5. Health check = the PC gateway answers over the tailnet (not only "the PC is on").
6. Optional: the watchdog texts Mark once on each switch ("Brice moved to the Mac").

Cases:
- PC boots while the Mac brain runs: the PC brain starts but has no lease, so it cannot hear
  or send texts. The lease moves to the PC only after Syncthing shows the PC is in sync.
  This also fixes the stale-memory window from the manual fail back.
- The Mac cannot reach the PC but the PC is fine (tailnet problem): the Mac takes the lease.
  The PC brain is fenced at the gate, so there is still only one voice.
- The Mac is off: no iMessage at all, for either brain. Failover does not help that case.
- Flapping: the 5-check and 3-check rules stop fast back-and-forth switching.

Not planned, and why:
- A cloud cron outside our machines: the lease must sit next to the gate. A cloud job adds a new
  thing that can control the gate.
- Watchdogs on both machines that both decide: two deciders can both pick themselves.

Known gaps:
- A fenced PC brain can still write memory from heartbeat or cron jobs (not from texts).
- Cron reminders live only on the host where they were made. They need their own design.
- Wake-on-LAN (row "Wake-on-LAN (Mac wakes PC)") is still deferred.

Work needed: gate change (security code, needs review), watchdog script, launchd plist, and a
drill. About half a day with review.

## Handoff: Brice-launched remote Claude Code sessions (2026-09-13)

Goal: when Mark texts Brice "launch a <project> Claude Code session with remote", Brice
opens a VISIBLE Warp window running a Claude Code session in that project's directory on the
correct machine, with remote control on, so Mark drives it from the Claude app on his phone
while AFK.

Decisions (from Mark):
- Trigger: Mark only, over iMessage. Remote-control sessions are tied to Mark's claude.ai
  account, so only he can attach even if the action is mis-triggered by another handle.
- Scope: one allowlisted "start session" action per project. NOT a general shell.
- Terminal: a VISIBLE Warp window on both machines (not a headless server).
- Workspace root is `~/workspace` on both machines; each repo lives under it.
- Projects: three. Two on the Mac (one is corporate), one on the PC. Keep the corporate
  project name and path out of this public repo - put the real map in the synced workspace
  (TOOLS.md / openclaw config), which both brains read.

Enablement: set `remoteControlAtStartup: true` so any `claude` session auto-enables remote
control at launch (no `/rc`, nothing to forget).

PC status / TODOs:
- DONE: `remoteControlAtStartup: true` set in PC `~/.claude/settings.json` (2026-09-13).
- DONE: PC project is Infopathy at `C:\Users\markr\workspace\infopathy-workspace`.
- DONE (2026-09-13): Windows host helper for Infopathy. Brice cannot reach the Windows GUI
  from its container, so `scripts/warp-launch-watcher.ps1` runs in Mark's user session (logon
  scheduled task `BriceWarpLaunchWatcher`, installed via `scripts/install-warp-watcher.ps1`).
  It watches `data/launch-triggers` (bind-mounted into the container) and, for an allowlisted
  project only, opens a visible Warp window running `claude` in that project's dir. Rate-limited
  1/project/60s; trigger CONTENT is ignored; only `claude` is ever launched (not a shell).
- TODO (PC Claude, part of S5): the Brice skill that drops the trigger / calls the Mac contract.

Mac Claude status (2026-09-13):
1. DONE: `remoteControlAtStartup: true` in `~/.claude/settings.json` and
   `~/.claude-corporate/settings.json` (backups next to each file). Checked: no API-key
   auth, proxy, or telemetry-off setting that would block Remote Control.
2. DONE: two Mac projects chosen by Mark. Keys in this repo: `mindr` (default Claude config)
   and `work` (corporate, `~/.claude-corporate`). The real folders are ONLY in the private
   map `~/.claude-launch/projects.json` (Mac) and in the synced workspace note
   `data/openclaw/workspace/CLAUDE-SESSIONS.md` (not in git).
3. DONE: launch gate `scripts/claude-launch-gate.py`, installed as
   `~/.claude-launch/claude-launch-gate`. Adversarial review done, findings fixed:
   - Accepts only `list` and `launch <key>`; keys come from the private map; paths must be
     ASCII and under `~/workspace`; config dir must be `~/.claude` or `~/.claude-corporate`.
   - Writes `~/.warp/launch_configurations/brice-<key>.yaml` and opens
     `warp://launch/brice-<key>.yaml` (a visible Warp window). Tested: an SSH login can open
     a Warp window and run a command (self-test PASS).
   - `mindr` runs `env -u CLAUDE_CONFIG_DIR command claude` (setting CLAUDE_CONFIG_DIR to
     ~/.claude would move the state file and show login prompts). `work` runs
     `CLAUDE_CONFIG_DIR=~/.claude-corporate command claude`.
   - Limits (file lock): 1 per project per 60s, 1 of any project per 5s, 10 per day.
   - A success means "launch requested", not "session ready".
   - Known and accepted: starting `claude` runs shell init and plugin SessionStart hooks
     in that folder, at a time the brain picks; the window is visible on the Mac screen.
4. DONE: invocation contract below.
5. DONE 2026-09-13 (Mark): launched `work` and `mindr` by hand through the gate. Both opened
   a Warp window with Claude ready (no login or trust prompt) and both showed up in the
   Claude app. `mindr` now points one level lower (the app folder inside the mindr dir;
   private map only).

Invocation contract (Mac projects):
```
ssh -T -i <launch key> -o IdentitiesOnly=yes -o BatchMode=yes \
    -o UserKnownHostsFile=<known_hosts> -o StrictHostKeyChecking=yes \
    mikee@100.67.66.94 <command>

<command> = list            -> {"ok": true, "projects": ["mindr", "work"]}
<command> = launch <key>    -> {"ok": true, "project": "<key>", "note": "launch requested; ..."}
                               {"ok": false, "error": "<reason>"}   (unknown project, limits, Warp)
```
- Windows OpenSSH needs `-o KexAlgorithms=curve25519-sha256` (same as the imsg key). Note:
  the container runs OpenSSH on Linux and does NOT need this flag (like imsg-over-ssh).
- The Mac host key and known_hosts are the same as for the imsg key.

Trigger contract (PC project - Infopathy):
```
# Brice, from inside the container, drops an empty file named after the project:
:> /home/node/.launch-triggers/infopathy
# The Windows host watcher opens a visible Warp window running `claude` in
# C:\Users\markr\workspace\infopathy-workspace, then deletes the trigger.
```
- Allowlist is in `scripts/warp-launch-watcher.ps1` ($Projects). Only `infopathy` today.
- Unknown project names are logged and discarded; nothing else runs.

| # | Who | Step | Status |
|---|---|---|---|
| S1 | PC | Make a SEPARATE key for launches, stored like the imsg key (Linux named volume, chmod 600, owned by uid 1000), comment exactly `brice-launch`. Never reuse the imsg key | DONE 2026-09-13 - key in `openclaw_launch_ssh` volume (600, uid 1000), comment `brice-launch`; mounted RO at `/home/node/.ssh-launch` |
| S2 | PC | Send ONLY the public key to the Mac: copy it to `pc-brice-launch.pub`, `tailscale file cp pc-brice-launch.pub macbook-air:`, delete the copy | DONE 2026-09-13 - public key Taildropped to macbook-air; local copy deleted |
| S3 | Mark (Mac) | Install it: `bash scripts/install-launch-key.sh <path to pc-brice-launch.pub>`. It adds `from="100.123.4.5",restrict,command=<launch gate>` and refuses a key already used for imsg | DONE 2026-09-13 - fingerprint SHA256:qYkp...n8lo installed with from/restrict/gate |
| S4 | PC | From the container, run the contract with `list`. Expect `["mindr","work"]`. Do NOT run `launch` yet | DONE 2026-09-13 - returned `{"ok":true,"projects":["mindr","work"]}` |
| S5 | PC | Brice skill + routing: Mark-only trigger; map "mindr"/"work" to the Mac contract, "infopathy" to the PC helper; read `CLAUDE-SESSIONS.md`; never a raw shell | DONE 2026-09-13 - `claude-launch <key>` wrapper (in the image; infopathy->PC trigger, mindr/work->Mac gate, refuses other keys) + `launch-claude-session` skill (ready) + CLAUDE-SESSIONS.md updated |
| S6 | Mark + PC | First real test: Mark texts Brice to launch `mindr`; confirm the Warp window opens on the Mac and the session shows in the Claude app | DONE 2026-09-13 - Mark confirmed: works perfectly (Warp window on the Mac + session in the Claude app) |
| P1 | PC | Infopathy host helper: watcher script + logon task installed and running; container has the trigger mount + launch key mount | DONE 2026-09-13 |
| P2 | Mark + PC | Test Infopathy: Brice drops trigger `infopathy`; confirm a visible Warp window opens running `claude` in `infopathy-workspace` and the session shows in the Claude app | DONE 2026-09-13 - end-to-end confirmed (Mark saw the window). Gotcha: Warp on Windows reads launch configs from Roaming (`%APPDATA%\warp\Warp\data\launch_configurations`), NOT Local |

Mac check for step 5 (Mark, at the Mac; opens a real session window):
`SSH_ORIGINAL_COMMAND="launch mindr" /usr/bin/python3 ~/.claude-launch/claude-launch-gate`

## Handoff: SMS failsafe for the family channel (2026-09-13)

Goal: when iMessage is unavailable (Mark or Kath on poor mobile data, so their text falls
back to green SMS), Brice should still receive and reply. The assistant's SIM iPhone (the
spare phone on the assistant Apple ID) is almost always next to the Mac, so its SMS can be
forwarded into the Mac's Messages and read by imsg.

Mark (iPhone, one time): on the spare assistant iPhone (AI SIM + assistant Apple ID),
Settings > Messages > Text Message Forwarding > enable the Mac. This routes SMS for the AI
number into the Mac's Messages.app. It was turned off during the Option B switch.

Mac Claude (gate change):
- Accept INBOUND SMS rows from the allowlisted family numbers (reuse the iMessage allowlist),
  not only iMessage-service rows.
- On OUTBOUND, reply over the SAME service the incoming used: if the incoming was SMS, reply
  by SMS; otherwise iMessage. Today the gate is iMessage-only outbound (no SMS fallback, PR
  #32) - relax that only for replying to an SMS conversation from an allowlisted number.
  Keep the allowlist; never open SMS to unknown numbers.

PC / OpenClaw: expected to need no change - the channel reads whatever imsg surfaces and the
family numbers are already allowlisted. Verify with one SMS test after the gate change (turn
Mark's iMessage off briefly, or text from a non-iMessage path).

Mac Claude status (2026-09-14): GATE CHANGE DONE AND INSTALLED.
- Inbound SMS already worked before the change: a forwarded SMS from Mark reached the brain
  (chat.db: service SMS, destination = assistant number) and the brain answered it. The old
  gate turned that answer into an iMessage.
- New outbound rule in `scripts/imsg-ssh-gate.py` (reviewed; findings fixed):

  | Person's LAST message to the assistant | On the family SMS list? | Reply |
  |---|---|---|
  | SMS or RCS | yes | SMS (if the SMS cannot even be addressed, iMessage instead; no double send) |
  | SMS or RCS | no (strangers, short codes, promos) | NO reply (the send is rejected) |
  | iMessage | - | iMessage (as before) |

- The family SMS list is private on the Mac (`~/.imsg-bridge/assistant.json`,
  `sms_allowed_handles`, built from `IMESSAGE_ALLOW_FROM`). Numbers are compared in E.164
  form, so `+63...`, `63...` and `09...` all match.
- The brain may ask for service `auto`, `imessage`, or `sms`; the gate picks the real one.
- The delivery check now matches the service and watches `error`/`is_sent`. A Messages
  delivery error comes back as "Delivery outcome unknown" with `retry_safe: false`.
- Side effect to know: a later proactive message (for example a reminder) uses the service
  of that person's LAST message. After Mark texts by SMS, he gets SMS until he uses iMessage.
- SMS goes out through the assistant iPhone's SIM, so it costs whatever that SIM plan charges.

| # | Who | Step | Status |
|---|---|---|---|
| SMS1 | Mark | Keep Text Message Forwarding on for the Mac on the assistant iPhone, and keep that iPhone powered and online (SMS in and out go through it) | DONE (inbound SMS seen 2026-09-14) |
| SMS2 | PC | `git pull`. No OpenClaw config change is expected. Check that `channels.imessage.allowFrom` holds the family numbers in `+63...` form (same form as the SMS handles). Do not print them | TODO |
| SMS3 | Mark + PC | Test: Mark turns iMessage OFF on his iPhone (Settings > Apps > Messages > iMessage), texts the assistant number (green bubble), expects a GREEN reply, then turns iMessage back ON | DONE 2026-09-14 17:50 - SMS in, SMS reply sent; Mark confirmed the green reply arrived |
| SMS4 | Mac | During SMS3, read `~/.imsg-bridge/gate.log` and chat.db: the reply row must be service SMS with no error | DONE 2026-09-14 - gate log `direct-send ok (1:1, SMS, ...)`, reply row service SMS, no error |
| SMS5 | PC | If OpenClaw logs a send error during SMS3, copy only the error text into this table (no numbers, no message text) | TODO |

## Handoff: model fallbacks, Claude primary (2026-09-14)

Goal: Claude stays the primary brain, but the assistant keeps working when Claude is down,
rate-limited, or the Anthropic spend cap is hit. Lowest cost, no Chinese-developed models,
and nothing that breaks a provider's terms of service.

Research summary (Mac Claude, 2026-09-14; sources are OpenClaw docs, OpenClaw GitHub issues,
provider pricing pages, and 2026 news. Items marked (2nd) came from secondary sites):
- OpenClaw failover keys: `agents.defaults.model.primary`, `agents.defaults.model.fallbacks`
  (ordered list), per-agent `agents.entries.<id>.model`, and `auth.order.<provider>`.
  Fallback triggers include auth errors, rate limits, overload, timeouts, billing disables,
  and model-not-found. Context overflow does NOT trigger a fallback.
- CLI: `openclaw models status [--probe]`, `openclaw models list --provider <id>`,
  `openclaw models set <provider/model>`, `openclaw models fallbacks list|add|remove|clear`.
  Check each with `--help` on the PC before using it.
- Terms of service:
  - BANNED: Claude Free/Pro/Max subscription login in OpenClaw (Anthropic), and Gemini CLI /
    Antigravity login (Google suspended accounts in Feb-Mar 2026). Never set these up.
  - GRAY (no written permission): ChatGPT Plus/Pro via Codex OAuth, GitHub Copilot as a model
    provider, SuperGrok / X Premium+ login. Not used in this plan.
  - SAFE: normal pay-per-use API keys (Anthropic, OpenAI, xAI, Mistral, Google API key,
    Bedrock, Vertex).
- Known OpenClaw problems: Gemini sometimes prints fake tool calls (issue #3344); Mistral tool
  calls fail with HTTP 400 on tool-call id format (#57672); rate-limit failover may not
  trigger (#57760); a fallback retry inserts a generic "Continue where you left off" user
  message (#65760). Small local models are prompt-injection prone (OpenClaw FAQ).
- Minors: Anthropic API terms are 18+; Google Gemini API terms forbid services likely to be
  used by under-18s; OpenAI allows 13+ with parental permission and asks for extra safeguards.
  Today only adults are on `allowFrom`. Do NOT add the kids as senders without a decision.
- Prices per 1M tokens, input/output: Claude Haiku 4.5 $1/$5; Claude Sonnet 5 $2/$10 (verify);
  Claude Sonnet 4.6 $3/$15 (2nd, verify); GPT-5-mini $0.25/$2; GPT-5-nano $0.05/$0.40.

Decision (recommended by Mac Claude; Mark to approve in M0):
```
primary     anthropic/claude-sonnet-5     existing Anthropic API key (only if M1 confirms id + price)
fallback 1  anthropic/claude-haiku-4-5    same key; covers Sonnet rate limits / overload
fallback 2  openai/gpt-5-mini             NEW OpenAI API key with a hard monthly limit;
                                          covers Anthropic outage or the Anthropic spend cap
heartbeat   anthropic/claude-haiku-4-5 + lightContext + isolatedSession (only if heartbeat is used)
NOT used    any subscription login, Gemini (tool-call bug + under-18 terms), Mistral (tool-call
            bug), Chinese-developed models, local models (prompt injection risk with tools)
```

| # | Who | Step | Status |
|---|---|---|---|
| M0 | Mark | Approve the chain above (or change it). Codex/ChatGPT subscription login stays OFF unless Mark accepts the gray-area risk in writing here | DONE 2026-09-14 - Mark approved the recommended chain as written (no subscription logins) |
| M1 | PC | `git pull`. Run `openclaw models status` and `openclaw models list --provider anthropic` and `--provider openai`. Record here: the exact ids for Sonnet 5, Haiku 4.5, GPT-5-mini, and the OpenClaw version. Check claude.com/pricing and developers.openai.com/api/docs/pricing and record the current prices | TODO |
| M2 | PC | In the installed OpenClaw version, check whether issues #57760 (rate-limit failover) and #65760 (fallback retry prompt) are fixed. Record the result | TODO |
| M3 | Mark | Create an OpenAI API key on platform.openai.com: prepaid credits with auto-recharge OFF (the credit balance is the hard cap), a project just for the assistant, a key in that project. Put it in the PC `.env` as `OPENAI_API_KEY` yourself (never in chat, never in git). A ChatGPT subscription does NOT include API credits | TODO |
| M4 | PC | Recreate the container so it reads the new `.env`: `docker compose up -d --force-recreate openclaw`. Then set the chain with the CLI (primary, then clear and add fallbacks in order). Do NOT use any subscription or OAuth login | TODO |
| M5 | PC | `openclaw models status --probe`: both providers must be healthy. Record the result (no keys) | TODO |
| M6 | PC + Mark | Fallback test without breaking Claude: in a PC chat session, `/model openai/gpt-5-mini -s`, ask one question that uses a tool (for example list chores), then switch back. Then Mark texts the assistant once to confirm iMessage replies still use Claude | TODO |
| M7 | PC | If heartbeat is used: set the heartbeat model to Haiku with `lightContext: true` and `isolatedSession: true` | TODO |
| M8 | Mac | Later, for failover to the Mac brain: copy `OPENAI_API_KEY` to the Mac `.env` over Taildrop (ties into L1) | TODO |

## Architecture (see docs/decisions/0001-architecture.md)
PC = always-on primary brain. Mac = warm backup brain + the "Apple bridge" for
iMessage and Apple Reminders. Tailscale connects PC/Mac/iPhone. Sync only the
Markdown memory; keep config/secrets per-host. Model routing: Sonnet default,
Opus escalation for hard/agentic tasks. Data lives only on the two machines.

## Phase 0 - Foundations (AS-1)
| Task | Status | Notes |
|---|---|---|
| Tailscale tailnet across PC/Mac/iPhone | DONE | PC = desktop-3p37btg / 100.123.4.5; Mac = macbook-air / 100.67.66.94 |
| Full-disk encryption (BitLocker/FileVault) | DEFERRED | Revisit on the Mac (portable) |
| CGNAT mobile-data reachability check | TODO | Open the tailnet URL on cellular |

## Phase 1 - Brain on the PC (AS-2)
| Task | Status | Notes |
|---|---|---|
| OpenClaw in Docker, always-on | DONE | healthy; restart unless-stopped |
| Claude API brain + Sonnet default | DONE | agents.defaults.model.primary = anthropic/claude-sonnet-4-6 |
| Memory read/write verified | TODO | quick "remember X / recall X" test |
| Harden (.env locked, non-admin user, unused channels off) | WIP | gateway token via env; non-admin user TODO |
| Reach over Tailscale | DONE | tailscale serve --http=18789 (loopback host bind) |
| LLM-egress note / local-model path | DONE | in the ADR |

## Phase 2 - Sync & failover, Mac backup brain (AS-3)
Runbook: docs/runbooks/mac-backup-brain.md (full from-scratch Mac onboarding).
| Task | Status | Notes |
|---|---|---|
| Syncthing mirror of the Markdown memory | WIP | first sync verified 25/25 files (2026-09-13); folder `openclaw-workspace` = data/openclaw/workspace; tailnet addresses only, relays + global discovery off. NOT verified yet: live updates, and restart after reboot. PC firewall TCP 22000 rule in place. PC starts Syncthing at user LOGIN (Startup-folder VBS), not at boot; Mac via `brew services` |
| Exclude SQLite index, rebuild on failover | WIP | the index is outside the shared workspace folder, so it does not sync; .stignore copied on both hosts as extra safety; rebuild not tested until the drill |
| Failover runbook + real drill | WIP | failover to the Mac tested 2026-09-15 (iMessage reply from the Mac brain); fail back pending (rows F1-F9) |
| Encrypted backup of the workspace | TODO | |
| Wake-on-LAN (Mac wakes PC) | DEFERRED | punted 2026-09-13; scripts/wake-pc.sh still needs the PC's Ethernet MAC address |

## Phase 3 - Voice PWA (AS-4)
| Task | Status | Notes |
|---|---|---|
| Installable PWA shell | DONE | pwa/ scaffold |
| Accent-robust STT (Deepgram vs gpt-4o-transcribe) | WIP | accent test - Mark to compare |
| Editable transcript before send | TODO | the accent-correction step |
| On-device TTS for replies | TODO | |
| Connect PWA to OpenClaw API | TODO | needs icons + wiring |

## Phase 4 - Custom skills (AS-5)
| Task | Status | Notes |
|---|---|---|
| Forgetful-notes (capture + recall) | TODO | the day-one win |
| Proactive reminders / briefings (cron -> iMessage/push) | TODO | AS-34 |
| Apple Reminders integration (Mac-side) | TODO | AS-35; timed reminders to iPhone |
| Family reminders | TODO | |
| Work integration | TODO | scope TBD (keep personal-side) |

## Phase 5 - Chores app integration via MCP (AS-26)
Runbook: docs/runbooks/chores-mcp-integration.md
| Task | Status | Notes |
|---|---|---|
| Connect brain to Chores MCP (POST /mcp) | DONE 2026-09-13 | mcp.servers.chore-app -> Railway backend /mcp; probe shows 6 tools |
| Store/rotate the Chores admin JWT | DONE (stored) 2026-09-13 | JWT in .env (gitignored); rotation steps in runbook |
| Voice intents: list_children / list_chores | TODO | read-only first |
| Voice intents: create_chore / post_from_template | TODO | read-back confirm |
| Voice intents: approve/reject + coin-move guard | TODO | spoken confirmation |
| Tie chores into notes/reminders | TODO | |

## Channels & persona
| Task | Status | Notes |
|---|---|---|
| iMessage family channel (free, imsg over Tailscale) | WIP | Option B assistant Apple ID on the Mac; container runs imsg over SSH through the gate; channel still OFF - see "Option B: identity switch" |
| Assistant name / persona + dedicated Apple ID (Option B) | WIP | dedicated Apple ID + number live in Messages on the Mac (2026-09-13); name not chosen |
| iPhone device pairing to the PC brain | TODO | open tailnet URL, pair, approve on PC |

## Decision: iMessage identity (2026-09-13)
UPDATE 2026-09-13 (later the same day): Mark switched to Option B. Option A below is
kept as history only. See "Option B: identity switch" for the current state.

Option A - Mark's personal Apple ID (was the prototype, now REPLACED)
- Works today. Messages on the Mac is already signed in.
- Risk: the brain can read every message Mark receives, from anyone.
- Risk: replies go out under Mark's name, so family cannot tell Mark from the bot.
- Risk: messages from non-family contacts may be sent to the Anthropic API.
- Keep it to testing. BLOCKER before the channel is turned on: limit senders with an
  allowlist (check the channels.imessage options in the OpenClaw docs).
- Test from a different Apple ID (e.g. Mark's wife's phone). A text from Mark's own
  iPhone is Mark to himself and will not test the bridge.

Option B - dedicated free Apple ID for the assistant (CHOSEN 2026-09-13)
- The assistant is its own contact. The brain only sees messages sent to it.
- Needs the assistant name first, because the Apple ID is created with it.
- Messages on one macOS user allows one iMessage account. Two ways to do it:
  - Switch this Mac's Messages to the new Apple ID (Mark's iMessages leave the Mac).
    <- this is what Mark did.
  - Or create a second macOS user for the assistant, kept logged in with fast user
    switching, so Mark keeps his own Messages. Untested: sending from a background
    user session may also fail with -1743.

## Open technical risks (found during Mac onboarding)
- SSH send (-1743): TESTED 2026-09-13 and it WORKS. OpenClaw docs warn about "Not
  authorized to send Apple events to Messages. (-1743)" for SSH wrappers. On this Mac,
  `ssh mikee@127.0.0.1 /opt/homebrew/bin/imsg send` delivered an iMessage to Mark's
  wife, and `imsg history` over SSH read her reply. Not tested yet: SSH from the PC over
  the tailnet, SSH from a container via host.docker.internal, and after a Mac reboot
  or while the screen is locked. The Mac user must stay logged in.
- The Mac's local test key was removed on 2026-09-13 after the PC key worked.
- The Mac brain cannot run imsg "locally". Docker on macOS runs Linux, and imsg is a
  macOS binary. A containerized Mac brain must also reach the Mac host over SSH
  (e.g. host.docker.internal), so the -1743 risk applies to both brains.
- The synced workspace contains a `.git` folder (OpenClaw's own). Syncthing copies it
  file by file. That is fine with one brain at a time, but a failover in the middle of
  a sync could leave a broken git index. Consider adding `.git` to .stignore on BOTH
  hosts (.stignore itself does not sync).
- The PC now has a Windows Firewall inbound rule for TCP 22000 (added on the PC, PR #15).
  If it was made with `-Profile Private` only, it may not cover the Tailscale adapter
  (Windows often puts it under Public) and it allows any private LAN. Check with
  `Get-NetConnectionProfile`. A tighter rule limited to the tailnet range:
  `New-NetFirewallRule -DisplayName 'Syncthing 22000 (tailnet)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22000 -RemoteAddress 100.64.0.0/10 -Profile Any`
- The PC Syncthing autostart VBS points at the versioned exe path. Update it after a
  Syncthing upgrade.
- SSH sessions need their own Full Disk Access entry
  (/usr/libexec/sshd-keygen-wrapper). The terminal's permission does not cover them.
  Already granted: imsg read chat.db over SSH on 2026-09-13.
- Over SSH, call imsg by full path (/opt/homebrew/bin/imsg). A non-interactive SSH
  command does not load the Homebrew PATH.

## Handoff: wire the PC brain to imsg over SSH  (status: Phase A DONE 2026-09-13, Phase B TODO)
Coordination: Mac Claude and PC Claude follow this section. Files that must not go in
git move over Taildrop (`tailscale file cp <file> <host>:`). Each side updates this
section when its part is done. Nobody sends an iMessage in this handoff.

What this phase does: the PC can run `imsg` on the Mac over SSH, with a key that is
locked down on the Mac. What it does NOT do: turn on the OpenClaw iMessage channel,
change docker-compose.yml, or restart the container. Those wait for the sender
allowlist and the container SSH plan (Phase B below).

Lock-down on the Mac (DONE by Mac Claude, tested 2026-09-13):
- `scripts/imsg-ssh-gate.py` is installed as `~/.imsg-bridge/imsg-ssh-gate`. It is the
  SSH forced command for the brain key. It never starts a shell. Why it is strict: sshd
  has Full Disk Access, so a free imsg could read ANY file (e.g. `send --file
  ~/.ssh/id_ed25519`) or delete messages on the personal Apple ID.
  - argv mode: only `chats`, `history`, `watch`, `send`, `status`; any option whose
    name has file/path/db/dylib/attach is denied.
  - rpc mode (OpenClaw uses `imsg rpc`, per its docs): the gate runs `imsg rpc` and
    filters each JSON-RPC line. Allowed methods: `initialize`, `status`, `chats.list`,
    `messages.history`, `messages.after`, `watch.subscribe`, `watch.unsubscribe`,
    `send`, `handles.check`. Any key with file/path/db/dylib/attach (at any depth) is
    denied. Lines with duplicate keys, NaN, a BOM, or over 1 MB are denied. The gate
    forwards its own re-encoded JSON, never the raw line (imsg keeps the FIRST
    duplicate key and Python the LAST, which was a real bypass found in review).
  - If imsg exits or the SSH client drops, the gate stops too, so nothing hangs.
  - Denials go to `~/.imsg-bridge/gate.log` (method names only, no message text).
    If OpenClaw needs a method we did not allow, the log shows it.
  - Tested 2026-09-13: chats and rpc `chats.list` work; `--file`, `--file=`, `--db`,
    `send-attachment`, `unsend`, `launch`, `rpc --db`, rpc `message.delete`,
    `send.attachment`, nested `FilePath` params, duplicate-key tricks, batch and
    non-JSON lines, shell injection, and scp are all denied.
  - Known gap: attachments are off. `imsg launch` (OpenClaw setup check) is denied.
- The PC key will be added as:
  `from="100.123.4.5",restrict,command="/Users/mikee/.imsg-bridge/imsg-ssh-gate" ssh-ed25519 ...`
  (`restrict` turns off pty, all forwarding, and ~/.ssh/rc)
- `scripts/imsg-over-ssh.sh` is the brain-side wrapper. It quotes each argument so text
  with spaces, quotes, and newlines reaches imsg unchanged (tested on bash 3.2; not yet
  on bash 5 or busybox).

Mac host key (check this before trusting the Mac):
`SHA256:EYJzw5MIsUCYbJ8P9fnDpqeHtUpVkSfd59ekfDo54KA` (ED25519)

| # | Who | Step | Status |
|---|---|---|---|
| 1 | PC | `git pull` on main | DONE (2026-09-13) |
| 2 | PC | Make the key folder and a key with no passphrase. Commands in block A below | DONE - key at data\openclaw-ssh\id_ed25519 (gitignored) |
| 3 | PC | Send ONLY the public key: copy `id_ed25519.pub` to `pc-brain-imsg.pub`, `tailscale file cp pc-brain-imsg.pub macbook-air:`, delete the copy. Never send the private key | DONE - sent to macbook-air via Taildrop |
| 4 | Mac | Install the key with the lock-down line above; send `mac-key-installed.txt` back | DONE - installed key matches VsIK...; sent back |
| 5 | PC | Build known_hosts and check the Mac fingerprint. Block B below. STOP if it is not the one above | DONE - host key MATCHES SHA256:EYJ...; had to force KexAlgorithms=curve25519-sha256 (see kex note) |
| 6 | PC | Read-only tests from Windows. Block C below | DONE - imsg read over SSH = ok; gate denies `id` ("only imsg may run") |
| 7 | PC | Read-only container check, no restart. Block D below. Also search the OpenClaw code in the container for the imsg rpc method names it sends (e.g. `chats.list`, `messages.history`, `watch.subscribe`, `send`, `initialize`) | DONE - container: bash+sed present, ssh MISSING, uid 1000, x86_64; rpc methods used = chats.list, messages.history, watch.subscribe, watch.unsubscribe (all in the gate allowlist) |
| 8 | PC | Send `pc-ssh-status.txt` to macbook-air (format below) | DONE - sent via Taildrop |
| 9 | Mac | Record results here; remove the local test key if no longer needed | DONE - results recorded; Mac test key removed, the PC key is the only imsg key |

PC status 2026-09-13 (PC Claude): steps 1-3 DONE. PC public key fingerprint
`SHA256:VsIK/J2FGcRSVhixQgNs552QC/pwgSFBCug6FFU00Yo` (`pc-brain-imsg`); public key
delivered to macbook-air via Taildrop. Private key lives at
`data\openclaw-ssh\id_ed25519` (gitignored, never sent). BLOCKED on step 4 - Mac to
install the key with the lock-down line and send `mac-key-installed.txt` back.

PC status UPDATE 2026-09-13 (PC Claude): steps 4-8 all DONE. Mac installed the
correct key (VsIK...). Host key verified = SHA256:EYJ... . imsg read over SSH from
the PC works; the gate denies `id`. Container: bash+sed present, `ssh` MISSING,
uid 1000, x86_64. OpenClaw rpc methods (chats.list, messages.history,
watch.subscribe, watch.unsubscribe) are all in the gate allowlist. `pc-ssh-status.txt`
sent to macbook-air. No iMessage sent; container untouched.

Two findings for Phase B:
1. KEX: the PC's Windows OpenSSH must force `-o KexAlgorithms=curve25519-sha256`
   (Mac sshd offers sntrup761x25519 which the Windows client can't negotiate). The
   wrapper `scripts/imsg-over-ssh.sh` and any container ssh must include this.
2. The container has NO ssh client. Phase B must add an ssh client to the image (or
   bridge to the Mac another way) before `channels.imessage.cliPath` can call imsg.

Mac notes 2026-09-13 (Mac Claude):
- gate.log on the Mac shows the PC's `id` test as a denial, so the from-IP match and the
  forced command both work over the tailnet.
- The Mac local test key is removed. `~/.ssh/authorized_keys` now holds only the PC key.
- KEX note correction: the curve25519 option is needed for the Windows OpenSSH client.
  A Linux OpenSSH client in the container (9.x) supports sntrup761x25519, so the wrapper
  should not force it by default. Add it only if the container test fails.
- How OpenClaw sends (rpc `send` or `imsg send`) is still unknown. The first send attempt
  shows up in `~/.imsg-bridge/gate.log` if the gate blocks it.

Commands for the PC (PowerShell, run from the repo folder; the repo path must have no
spaces):

Block A - key (PowerShell drops an empty `""` argument, so ssh-keygen runs through cmd):
```powershell
New-Item -ItemType Directory -Force data\openclaw-ssh | Out-Null
cmd /c 'ssh-keygen -t ed25519 -N "" -C pc-brain-imsg -f data\openclaw-ssh\id_ed25519'
Copy-Item data\openclaw-ssh\id_ed25519.pub pc-brain-imsg.pub
tailscale file cp pc-brain-imsg.pub macbook-air:
Remove-Item pc-brain-imsg.pub
```

Block B - known_hosts (PowerShell `>` writes UTF-16, which ssh cannot read):
```powershell
ssh-keyscan -t ed25519 100.67.66.94 | Out-File -Encoding ascii data\openclaw-ssh\known_hosts
ssh-keygen -lf data\openclaw-ssh\known_hosts
```

Block C - read-only tests (never run `imsg send` here):
```powershell
$k  = "data\openclaw-ssh\id_ed25519"
$kh = "data\openclaw-ssh\known_hosts"
ssh -T -i $k -o IdentitiesOnly=yes -o UserKnownHostsFile=$kh -o StrictHostKeyChecking=yes mikee@100.67.66.94 /opt/homebrew/bin/imsg chats --limit 1
# expect: one chat line (do not copy it anywhere, it has a phone number)
ssh -T -i $k -o IdentitiesOnly=yes -o UserKnownHostsFile=$kh -o StrictHostKeyChecking=yes mikee@100.67.66.94 id
# expect: imsg-ssh-gate: denied: only imsg may run
```

Block D - container tools (read-only):
```powershell
docker exec openclaw sh -c 'for t in ssh bash sed; do printf "%s=" "$t"; command -v "$t" || echo missing; done; id -u; uname -m'
```

`pc-ssh-status.txt` format (plain text, NO secrets, NO phone numbers - do not copy the
imsg output, it contains numbers):
```
key_fingerprint=<SHA256 of the PC public key>
mac_hostkey_match=yes|no
imsg_read_test=ok|failed: <error>
gate_denies_id=yes|no: <output>
container_ssh=<path or missing>
container_bash=<path or missing>
container_sed=<path or missing>
container_uid=<n>
container_arch=<arch>
openclaw_rpc_methods=<comma list, or unknown>
errors=none|<short text>
```

Phase B (later, not in this handoff):
- Sender control: OpenClaw docs say iMessage DMs default to pairing mode (`dmPolicy`),
  so a new sender must be approved first. Confirm it is on before enabling (BLOCKER).
- Add an ssh client to the container (it has none). Options: a small custom image
  (`FROM ghcr.io/openclaw/openclaw:<pinned>` + `openssh-client`), or install at start.
  Pin the base image first (docker-compose.yml still uses `:latest`).
- Get the key and wrapper into the container. A Windows bind mount shows files as 0777,
  and ssh refuses a private key like that. Plan: copy the key to a container-only path
  with `chmod 600` at start, or install the image's ssh client if it is missing.
- Set `IMSG_SSH_TARGET`, `IMSG_SSH_KEY`, `IMSG_SSH_KNOWN_HOSTS`, point
  `channels.imessage.cliPath` at the wrapper, enable the channel, restart, test with the
  wife's phone.
- Attachments: the gate blocks scp, so attachments stay off until we design for them.

PC Phase B progress 2026-09-13 (PC Claude), identity choice = Option A guarded test:
- Custom image `assistant/openclaw:with-ssh` built (Dockerfile.imsg): pinned OpenClaw
  base digest + openssh-client + the imsg-over-ssh wrapper (CR stripped; .gitattributes
  keeps *.sh/*.py LF). `.dockerignore` keeps secrets out of the build.
- SSH key in a Linux-native named volume `openclaw_imsg_ssh` (id_ed25519 chmod 600 +
  known_hosts, owned uid 1000), mounted read-only at /home/node/.ssh-imsg. Avoids the
  Windows-bind-mount 0777 problem.
- docker-compose.yml switched to the custom image (build:) + the ssh volume; `.env` has
  IMSG_SSH_TARGET=mikee@100.67.66.94, IMSG_SSH_KEY, IMSG_SSH_KNOWN_HOSTS (per-host,
  gitignored). Container recreated, healthy.
- VERIFIED: `docker exec openclaw /usr/local/bin/imsg-over-ssh chats --limit 1` returns
  data (exit 0) - the container can drive imsg on the Mac through the gate. Read-only.
- REMAINING to enable the channel: (1) Mark's wife's handle for
  `channels.imessage.allowFrom` (dmPolicy=allowlist so only family is processed),
  (2) set channels.imessage.cliPath=/usr/local/bin/imsg-over-ssh + enable, (3) test from
  the wife's phone. Channel still OFF; no iMessage sent.

## Option B: identity switch  (status: WIP, 2026-09-13)
The repo is PUBLIC. Never write the assistant's email or number, or any family phone
number, in this file, in commits, or in PR text. They live only in each brain host's
`.env` (gitignored) and move between hosts over Taildrop.

Private values (names only):
- `ASSISTANT_IMESSAGE_EMAIL` - the assistant's Apple ID email (Messages app only).
- `ASSISTANT_IMESSAGE_NUMBER` - the assistant's phone number, registered for iMessage.
- `IMESSAGE_ALLOW_FROM` - comma list of family handles the brain may act on (Mark's
  phone and Apple ID email, and Mark's wife's phone).

Mac state (Mac Claude, verified 2026-09-13):
- Messages > Settings > iMessage shows the assistant Apple ID. Reachable at the
  assistant number and email. New conversations start from the assistant number.
  Messages in iCloud is OFF.
- A test iMessage from Mark's iPhone arrived on the assistant account and number
  (chat.db `account` and `destination_caller_id`). `imsg rpc chats.list` sees it.
- The Mac `.env` has the three private values above.
- Note: `~/Library/Preferences/com.apple.madrid.plist` still lists Mark's old addresses.
  That file lags. Trust Messages settings and chat.db instead.
- Nothing changes in the gate or the wrapper. imsg sends from whatever account Messages
  is signed in to.

| # | Who | Step | Status |
|---|---|---|---|
| 1 | Mac | Send `assistant-identity.env` (the three private values) to the PC over Taildrop | DONE |
| 2 | PC | `git pull`. Find `assistant-identity.env` (Downloads or `tailscale file get`). Append its three lines to the PC `.env`, then delete the received file. Do not print the values in chat or commit them | TODO |
| 3 | PC | Set `channels.imessage.allowFrom` from `IMESSAGE_ALLOW_FROM` (dmPolicy=allowlist). Do NOT add the assistant's own email or number (reply-loop risk). Keep the values in openclaw.json only, never in git | TODO |
| 4 | PC | Set `channels.imessage.cliPath=/usr/local/bin/imsg-over-ssh`, enable the channel, restart the container | TODO |
| 5 | PC + Mark | Test 1: Mark texts the assistant NUMBER from his iPhone. This is a real test now, because Mark's phone is a different Apple ID. Expect a reply from the assistant | DONE 2026-09-13 18:32 - reply received |
| 6 | Mac | During test 1, watch `~/.imsg-bridge/gate.log`. If OpenClaw's send is denied, add the needed method to the gate allowlist after review | TODO |
| 7 | PC + wife | Test 2: Mark's wife texts the assistant number. OPTIONAL for now: Mark's own iPhone is a valid tester after the switch | TODO (optional) |
| 8 | PC | Send `pc-optionb-status.txt` to macbook-air: allowFrom count (not values), channel enabled yes/no, test 1 and 2 results, errors. No handles, no message text | TODO |

Open issues for Option B (need Mark's decision or action):
- OLD PERSONAL HISTORY: DONE with a gate filter, nothing deleted (Mark chose (b) on
  2026-09-13, so no risk of a delete syncing to his iPhone). chat.db still holds Mark's
  old history (529 chats, about 11,000 messages), but the gate hides it:
  - Private config on the Mac: `~/.imsg-bridge/assistant.json` (assistant handles +
    `visible_since_utc`, the switch time). Not in git.
  - A message is visible only if its chat.db `account` or `destination_caller_id` is an
    assistant handle AND it is newer than the switch. The gate checks every
    `chats.list` chat, every `messages.history` / `messages.after` message, and every
    watch `message` notification against chat.db. A quoted old message
    (`reply_to_text`) is blanked. Unknown output with message content is hidden.
  - Fail closed: no config or a failed check hides the data.
  - Tested on the Mac: raw imsg showed 50 chats; through the gate only the assistant
    chat. Chat 1 raw [new + 2 old] -> gated [new]. The wife's old chat -> empty.
    `messages.after` 47 raw -> 1 gated (cursor kept). Watch replay hid 12 old messages.
  - argv mode now allows only `send` and `status` (plain-text output cannot be
    filtered). The PC check `imsg-over-ssh chats --limit 1` is now DENIED on purpose.
    To test reads from the PC, use rpc, e.g.
    `echo '{"jsonrpc":"2.0","id":1,"method":"chats.list","params":{"limit":5}}' | docker exec -i openclaw /usr/local/bin/imsg-over-ssh rpc`.
  - Review round (2026-09-13) found two leak paths in reply matching (an id-less
    request, and two requests with the same id). Fixed: the gate now filters every
    reply by its shape (any `chats` or `messages` it contains), not by the request it
    claims to answer. Requests must have an integer or string id. `handles.check` was
    removed. A cutoff earlier than 2026-09-13 or in the future hides everything. Both
    attacks were re-tested and return no old messages.
  - Known limits: sender and participant names can come from the Mac's Contacts (Mark's
    address book). A tapback on an old message could quote a short snippet. Both are
    accepted for now.
- SMS FORWARDING: RESOLVED 2026-09-13. The iPhone no longer lists the Mac for Text
  Message Forwarding, and no SMS rows arrived on the Mac since the switch. The gate also
  denies SMS sends.
- The PC Phase B notes above say "identity choice = Option A guarded test". That is
  replaced by this section. allowFrom now protects the assistant account, and Mark is a
  valid tester.

PC go-live attempt 2026-09-13 (PC Claude):
- Steps 2-3 DONE: identity in PC .env (values not printed/committed), dmPolicy=allowlist,
  allowFrom=3 handles, cliPath=/usr/local/bin/imsg-over-ssh set. rpc read pre-check
  returned exactly 1 chat (assistant account; gate hides old history - confirmed).
- Step 4 attempted: restarted the container; the imessage plugin loaded and started the
  provider, but it FAILED to connect and auto-restart-looped. Channel is enabled in
  config but not running. Mark did NOT text (step 5 held).
- Two gate denials block startup (need Mac gate changes; details sent to macbook-air in
  pc-optionb-status.txt over Taildrop):
  1) `imsg rpc --help` (OpenClaw readiness probe) -> "rpc option '--help' is not allowed".
  2) `watch.subscribe` -> "file or path parameter in 'watch.subscribe' code=-32601": the
     file/path/db/attach key filter blocks a benign watch.subscribe param (likely
     attachments / dbPath / since_rowid / include_reactions). See ~/.imsg-bridge/gate.log.
- HANDOFF to Mac: update the gate to allow `rpc --help` and OpenClaw's watch.subscribe
  params, reinstall on the Mac, then tell PC to `docker compose restart openclaw` and
  retry test 1. (Mac already pushed a small gate change; awaiting confirmation it is
  installed and covers both.)

Mac reply + go-live retry 2026-09-13 (Mac Claude). Gate fixes, all installed on the Mac:
- `imsg rpc --help` / `-h` allowed (usage text only). PR #24.
- `watch.subscribe`: the blocked key was `attachments` with value false. Attachment
  switches are now allowed when exactly `false`; `true` is still denied. PR #25.
- imsg errors are no longer hidden. Every JSON-RPC error has a `message` key, which the
  content check wrongly treated as an iMessage. The gate now passes the error `code`,
  `message`, and a short string `data` (the reason). PR #27.
- `send-rich` (argv) stays DENIED on purpose: it needs SIP off + dylib injection, which
  this Mac does not have (`imsg status`: advanced features not available). OpenClaw
  should fall back to plain `send`. If it does not, tell the Mac.

What happened on retry 1 (Mac view):
- After the restart, the provider connected: a gate session opened and `watch.subscribe`
  worked.
- 17:54:25 Mark's iPhone texted the assistant number. The Mac received it on the
  assistant account (test 1 inbound = PASS).
- 17:54:38 OpenClaw's reply attempt got an imsg ERROR, which the old gate hid. No reply
  was sent. The gate session that handled it still runs the OLD gate code, so the
  real error text is not known yet.

| # | Who | Step | Status |
|---|---|---|---|
| R1 | PC | `git pull`, then `docker compose restart openclaw` (a new bridge session picks up the fixed gate) | DONE |
| R2 | PC | Confirm the iMessage provider starts and stays up (no restart loop) | DONE - up + stable; no rpc --help / attachments denials; watch.subscribe OK; no restart loop |
| R3 | PC | Tell Mark to text the assistant number again from his iPhone | DONE - Mark texted; inbound received; Sonnet reply generated |
| R4 | PC | If no reply: read the OpenClaw log for the reply attempt and copy only the error text (the gate now passes imsg's reason, e.g. `Invalid params` + `unknown send param: x`). No handles, no message text | DONE - outbound FAILED: "OutboundDeliveryError: Delivery failed before dispatch: code=-32603" (JSON-RPC internal error; reply not delivered) |
| R5 | PC | Check which method OpenClaw used to reply: rpc `send`, `send.tracked`, or argv `imsg send` / `send-rich`. The gate allows only rpc `send` and argv `send` | PARTIAL - method not shown in PC logs at default verbosity; Mac gate.log has method+reason. Hypotheses: rich-send unsupported on this Mac (no SIP/dylib) with no fallback, or rpc send param (region PH/+63, or reply_to threaded needs bridge) |
| R6 | PC | Send `pc-optionb-status.txt` to macbook-air with R2-R5 results. The Mac Claude also reads `~/.imsg-bridge/gate.log`, which now logs `imsg-error code=... message | reason` | DONE - sent to macbook-air (no handles/text). Awaiting Mac to read gate.log and tell PC what to change on the OpenClaw side (PC will not touch the gate) |

Notes for the reply path (from imsg v0.15.4 source):
- rpc `send` accepts: `to`, `text`, `file` (denied by the gate), `service`, `transport`,
  `region`, `allow_sms_fallback`, `reply_to`, and chat target keys. Anything else gives
  `Invalid params`.
- `send.tracked` needs the bridge transport (not available on this Mac) and is not in
  the gate allowlist.
- `region` defaults to `US`. Philippine numbers may need `region: "PH"` or `+63` format.
- `reply_to` (a threaded reply) may need the bridge. If the error mentions bridge or
  reply, turn threaded replies off in OpenClaw's iMessage config.

Go-live result 2026-09-13 18:32 (Mac Claude): END-TO-END REPLY WORKS.
Chain: Mark's iPhone -> assistant number -> Messages on the Mac -> gate -> PC brain ->
gate -> Messages (from the assistant number) -> Mark's iPhone. Nothing was changed on
the PC after its restart; every fix was in the Mac gate (PRs #24, #25, #27, #29, #31,
#32, #33), and OpenClaw reconnected by itself after each gate install.

What had to be fixed, in order:
1. `imsg rpc --help` probe was denied -> allowed (usage text only).
2. `watch.subscribe` with `attachments:false` was denied -> false switches allowed.
3. imsg errors were hidden (the JSON-RPC `message` key looked like content) -> error
   code, message, and reason fields now pass and are logged.
4. OpenClaw sends replies as threaded replies (`reply_to`), which need imsg's bridge
   (SIP off + dylib) -> the gate strips `reply_to`; replies arrive as plain messages.
5. imsg always resolves a 1:1 send to the existing chat in chat.db. For Mark that chat
   belongs to his OLD Apple ID, and Messages cannot find it (AppleScript -1728); Messages
   only exposes the merged SMS chat. -> For a 1:1 chat whose person has already messaged
   the assistant, the gate sends itself (AppleScript: send to buddy on the iMessage
   service). Other sends still go to imsg.
6. All sends are iMessage only (`allow_sms_fallback=false`, `service: sms` denied),
   because SMS on this Mac can go out through Mark's iPhone.

Known limits and follow-ups:
- In chat.db the reply row shows Mark's OLD account in `account`, but
  `destination_caller_id` (the sending address) is the assistant number. Mark CONFIRMED
  on his iPhone that the reply came from the assistant number.
- Group chats: sends denied by the gate for now.
- Attachments and threaded replies are off.
- `send-rich` stays denied (no bridge on this Mac).
- The gate fixes #24-#33 were merged with local tests but WITHOUT the adversarial review
  from CLAUDE.md. The post-hoc review found real holes, now fixed in the same PR as this
  note:
  - argv `imsg send` skipped every guard (SMS to anyone was possible). argv mode now
    allows only `status`.
  - rpc `send` with no eligible target was forwarded to imsg unchanged (strangers, old
    chats, possible SMS). Now the gate never forwards `send` to imsg. It sends itself,
    only to a 1:1 chat whose person has sent an inbound message to the assistant account
    after the switch. The assistant's own outgoing messages do not count.
  - `service` must be missing, `auto`, or `imessage`.
  - After a send the gate looks for the sent row in chat.db (up to 8s) and returns its
    id and guid. Otherwise it returns "Delivery outcome unknown" with `retry_safe: false`
    so the brain does not send twice.
  - The log keeps only AppleScript error numbers; quoted strings in errors are blanked.
  - One lock around the chat.db connection; the chat lookup filters 1:1 rows.
  - Group chats: sends are now denied (not supported).
  - Tested without sending: strangers, old chats (by id and by handle), groups, and
    ` sms`/`SMS` denied; the eligible chat passes; reads and strict parsing unchanged.
- PC cleanup (optional): turn off threaded replies in OpenClaw's iMessage config, so the
  gate does not need to strip `reply_to`; `git pull`.
- Mark's wife test (step 7): optional, not done yet.
- SMS forwarding to this Mac: effectively OFF (2026-09-13). The iPhone no longer lists the
  Mac (different Apple IDs for Messages), and no SMS rows arrived since the switch. The
  Mac's SMS account label still says "connected"; ignore it. The gate also blocks SMS.
- Do not install the pending macOS update until the bridge is stable; updates can reset
  Full Disk Access and Automation permissions.

## Runbooks
- docs/runbooks/openclaw-on-windows.md - PC brain (Docker, harden, Tailscale serve)
- docs/runbooks/mac-backup-brain.md - Mac from-scratch: backup brain + iMessage bridge
- docs/runbooks/imessage-mac-setup.md - free iMessage via imsg over Tailscale
- docs/runbooks/chores-mcp-integration.md - Chores app MCP wiring
- docs/decisions/0001-architecture.md - architecture decisions

---

# Ticket details (full specs)

Full detail for the three key coordination items, kept here so nothing depends on
Jira. AS-xx are historical labels only.

## AS-3 - Sync and failover: PC primary, Mac warm backup  (status: WIP)
Phase 2. Mirror the brain memory from the PC to the Mac so the Mac can take over as
backup brain, AND ensure the family can iMessage whichever brain is active.

Goal (per Mark): Mark and his wife text the assistant from their phones and get tasks
done regardless of which brain is running it. The iMessage bridge (imsg) lives on the
always-on Mac; the active brain connects to it - the PC brain over SSH/Tailscale, the Mac brain over SSH to its own host (host.docker.internal), because a Linux container cannot run the macOS imsg binary. Exactly one brain runs at a time, so exactly one owns the iMessage
connection.

Approach: sync ONLY the Markdown memory workspace (the source of truth) via Syncthing;
keep openclaw.json and .env per-host. Both hosts use an SSH wrapper as cliPath; only
the SSH target differs; the SQLite index is derived and rebuilt on failover.

Runbook: docs/runbooks/mac-backup-brain.md (and imessage-mac-setup.md).

Sub-tasks: Syncthing mirror; SQLite exclude/rebuild; failover runbook + drill;
encrypted backup; Wake-on-LAN (deferred).

Exit criteria: near-real-time memory mirror on both machines; a tested failover;
iMessage works from both PC-active and Mac-active states.

## AS-12 - iMessage family channel (free) via imsg over Tailscale  (status: WIP)
Free iMessage channel for the family - $0, no paid API. The Mac is the Apple bridge;
the brain stays on the PC.

Approach: OpenClaw's iMessage channel uses the free imsg CLI on the Mac, which reads
~/Library/Messages/chat.db and sends via Messages.app. The PC gateway calls imsg on
the Mac over Tailscale via SSH (attachments via SCP). imsg, iMessage, Tailscale, and
SSH are all free.

Mac-side (Mark, at the machine): install Homebrew + imsg, sign Messages into
Mark's personal Apple ID for the prototype (Option A; dedicated Apple ID later, Option B), enable Remote
Login, grant Full Disk Access + Automation, verify `imsg chats --limit 1`.

PC-side (Claude): passwordless SSH key PC->Mac over Tailscale, a cliPath wrapper that
runs imsg over SSH, set channels.imessage.cliPath + enable the channel, restart the
gateway, test.

Cross-brain requirement: family must be able to iMessage whichever brain is active.
One Apple ID signed into Messages on the Mac (personal now, dedicated later); the imsg
bridge lives on the always-on Mac; the active brain connects to it - the PC brain over SSH/Tailscale, the Mac brain over SSH to its own host (host.docker.internal), because a Linux container cannot run the macOS imsg binary
(per-host cliPath, since config is not synced). Exactly one brain runs at a time.

Catches: see "Decision: iMessage identity" for Option A risks; fragile across macOS updates/reboots (Full
Disk Access resets); Apple gray area (not sanctioned, fine with Anthropic and free);
Full Disk Access is powerful. Runbook: docs/runbooks/imessage-mac-setup.md.

## AS-16 - Write and test the failover runbook (one-brain-at-a-time)  (status: WIP)
Document the steps to promote the Mac to backup brain when the PC is down, including
the hard rule that only one brain runs at a time. Do a real drill: stop the PC brain,
start the Mac brain, confirm memory is current, then fail back.

Progress: runbook prepared and committed - docs/runbooks/mac-backup-brain.md (now a
full from-scratch Mac onboarding, steps tagged [CLI] vs [GUI/You] so Claude Code on
the Mac can drive it). Covers Mac setup (Docker, Syncthing memory-only mirror, per-host
config/secrets), failover, Wake-on-LAN (deferred), encrypted backup, and the cross-brain
iMessage design.

The SSH send test (-1743) passed on the Mac itself (2026-09-13). Still to test before
the drill: the same send from the PC over the tailnet, and from the Mac container.

Remaining to close: run a real drill (stop PC brain, start Mac brain, confirm memory
current + iMessage still works, then fail back).
