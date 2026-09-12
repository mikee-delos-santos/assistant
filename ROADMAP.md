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
- The Mac has not been onboarded yet; from-scratch runbook is ready.
- Assistant name / persona: NOT chosen yet (it becomes the iMessage contact name).

## Architecture (see docs/decisions/0001-architecture.md)
PC = always-on primary brain. Mac = warm backup brain + the "Apple bridge" for
iMessage and Apple Reminders. Tailscale connects PC/Mac/iPhone. Sync only the
Markdown memory; keep config/secrets per-host. Model routing: Sonnet default,
Opus escalation for hard/agentic tasks. Data lives only on the two machines.

## Phase 0 - Foundations (AS-1)
| Task | Status | Notes |
|---|---|---|
| Tailscale tailnet across PC/Mac/iPhone | DONE | PC = desktop-3p37btg / 100.123.4.5 |
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
| Syncthing mirror of the Markdown memory | TODO | memory-only; config/secrets per-host |
| Exclude SQLite index, rebuild on failover | TODO | config/openclaw-home.stignore |
| Failover runbook + real drill | WIP | runbook written; drill pending |
| Encrypted backup of the workspace | TODO | |
| Wake-on-LAN (Mac wakes PC) | TODO | scripts/wake-pc.sh (fill MAC) |

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
| iMessage family channel (free, imsg over Tailscale) | TODO | runbook: docs/runbooks/imessage-mac-setup.md; works on whichever brain is active |
| Assistant name / persona + dedicated Apple ID | TODO | the contact name family sees |
| iPhone device pairing to the PC brain | TODO | open tailnet URL, pair, approve on PC |

## Runbooks
- docs/runbooks/openclaw-on-windows.md - PC brain (Docker, harden, Tailscale serve)
- docs/runbooks/mac-backup-brain.md - Mac from-scratch: backup brain + iMessage bridge
- docs/runbooks/imessage-mac-setup.md - free iMessage via imsg over Tailscale
- docs/runbooks/chores-mcp-integration.md - Chores app MCP wiring
- docs/decisions/0001-architecture.md - architecture decisions
