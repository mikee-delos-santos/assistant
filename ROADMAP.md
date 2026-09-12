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
  The Mac container stays STOPPED (PC is the active brain).
- iMessage runs as a PROTOTYPE on Mark's personal Apple ID (Option A, see
  "Decision: iMessage identity" below). Dedicated Apple ID (Option B) is planned.
- Assistant name / persona: NOT chosen yet (it becomes the iMessage contact name
  once we move to Option B).

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
| Failover runbook + real drill | WIP | runbook written; drill pending |
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
| Connect brain to Chores MCP (POST /mcp) | TODO | needs admin JWT |
| Store/rotate the Chores admin JWT | TODO | full family admin secret |
| Voice intents: list_children / list_chores | TODO | read-only first |
| Voice intents: create_chore / post_from_template | TODO | read-back confirm |
| Voice intents: approve/reject + coin-move guard | TODO | spoken confirmation |
| Tie chores into notes/reminders | TODO | |

## Channels & persona
| Task | Status | Notes |
|---|---|---|
| iMessage family channel (free, imsg over Tailscale) | WIP | prototype on personal Apple ID (Option A); Mac side installed, imsg reads chats; SSH send (-1743) not tested yet |
| Assistant name / persona + dedicated Apple ID (Option B) | TODO | future; move off the personal Apple ID before real family use |
| iPhone device pairing to the PC brain | TODO | open tailnet URL, pair, approve on PC |

## Decision: iMessage identity (2026-09-13)
Prototype with Option A now. Plan to move to Option B later.

Option A - Mark's personal Apple ID (CHOSEN for the prototype)
- Works today. Messages on the Mac is already signed in.
- Risk: the brain can read every message Mark receives, from anyone.
- Risk: replies go out under Mark's name, so family cannot tell Mark from the bot.
- Risk: messages from non-family contacts may be sent to the Anthropic API.
- Keep it to testing. BLOCKER before the channel is turned on: limit senders with an
  allowlist (check the channels.imessage options in the OpenClaw docs).
- Test from a different Apple ID (e.g. Mark's wife's phone). A text from Mark's own
  iPhone is Mark to himself and will not test the bridge.

Option B - dedicated free Apple ID for the assistant (FUTURE)
- The assistant is its own contact. The brain only sees messages sent to it.
- Needs the assistant name first, because the Apple ID is created with it.
- Messages on one macOS user allows one iMessage account. Two ways to do it:
  - Switch this Mac's Messages to the new Apple ID (Mark's iMessages leave the Mac).
  - Or create a second macOS user for the assistant, kept logged in with fast user
    switching, so Mark keeps his own Messages. Untested: sending from a background
    user session may also fail with -1743.

## Open technical risks (found during Mac onboarding)
- SSH send may fail. OpenClaw docs list "Not authorized to send Apple events to
  Messages. (-1743)" for SSH wrappers. Their fix is to run the imsg bridge in the
  logged-in user's session. Test a send over SSH before trusting the PC-to-Mac design.
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
  Not granted yet. Only Warp has Full Disk Access so far.
- Over SSH, call imsg by full path (/opt/homebrew/bin/imsg). A non-interactive SSH
  command does not load the Homebrew PATH.

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

Blocker: the SSH send test (-1743) must pass before the drill can prove iMessage works
on both brains.

Remaining to close: run a real drill (stop PC brain, start Mac brain, confirm memory
current + iMessage still works, then fail back).
