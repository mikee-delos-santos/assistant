# Mac warm-backup brain (with iMessage on whichever brain is active)

Goal: run OpenClaw on the Mac as a warm backup to the PC brain, and make iMessage
work no matter which brain is currently active - so Mark and his wife can text the
assistant from their phones and get tasks done whether the PC or the Mac is running
it. Covers AS-3 (epic) and stories AS-14, AS-15, AS-16, AS-17, AS-33, and ties into
AS-12 (iMessage).

## Core principle: exactly one brain at a time
Never run the PC and Mac gateways simultaneously - two live brains writing the same
memory is split-brain. The Mac container stays STOPPED during normal operation and
is only started when the PC is down. Exactly one brain owns the iMessage connection
at any moment.

## Data model (what syncs, what doesn't)
- SYNC: only the Markdown memory workspace (`data/openclaw/workspace`). This is the
  source of truth and mirrors PC <-> Mac in near-real-time via Syncthing.
- DO NOT SYNC: `openclaw.json` (config) and `.env` (secrets) stay per-host, and the
  SQLite index is derived (excluded; rebuilt from Markdown on start). Keeping config
  per-host is what lets each machine wire iMessage differently (see below).

## iMessage across both brains (the key design)
The iMessage bridge is the free `imsg` CLI on the Mac (see docs/runbooks/imessage-mac-setup.md).
Both brains use that same Mac bridge, but reach it differently:
- PC brain (normal): `channels.imessage.cliPath` = a wrapper that SSHes to the Mac
  over Tailscale and runs `imsg`.
- Mac brain (failover): `channels.imessage.cliPath` = local `imsg` (no SSH).
Because config is per-host (not synced), each machine keeps its own correct cliPath.
There is ONE assistant Apple ID; the family texts it and whichever brain is active
answers. Multiple senders (Mark + wife) get their own sessions automatically.

## Mac-side setup (one-time, at the Mac)
1. Install Docker Desktop for Mac and confirm it runs.
2. `git clone https://github.com/mikee-delos-santos/assistant` (or pull latest). It
   has docker-compose.yml and config/openclaw-home.stignore.
3. Create the Mac's own `.env` (NOT synced): same ANTHROPIC_API_KEY and
   OPENCLAW_GATEWAY_TOKEN as the PC. Keep it local; it's gitignored.
4. Install Syncthing (`brew install syncthing` or the app). Pair with the PC's
   Syncthing and share ONLY the memory folder (`data/openclaw/workspace`). Use
   config/openclaw-home.stignore as the folder's `.stignore` (excludes SQLite/logs).
5. Confirm memory files appear on the Mac and update within seconds when the PC
   changes them.
6. Do the iMessage Mac setup from docs/runbooks/imessage-mac-setup.md (Homebrew,
   imsg, Remote Login, Full Disk Access/Automation, dedicated Apple ID).
7. DO NOT start the container yet - starting it now would be a second live brain.

## Failover: promote the Mac to backup brain (PC is down)
1. Confirm the PC gateway is actually stopped (no two brains).
2. On the Mac: `docker compose up -d`. The SQLite index rebuilds from synced Markdown
   on first start. The Mac's local `imsg` cliPath means iMessage keeps working.
3. Reach it over Tailscale like the PC (Control UI / tailscale serve), or
   `docker exec -it openclaw openclaw chat`.
4. When the PC returns: `docker compose stop openclaw` on the Mac, let Syncthing
   reconcile, then start the PC brain again.

## Prefer waking the PC over failing over (AS-33)
If the PC is asleep/off, the Mac can send a Wake-on-LAN packet (scripts/wake-pc.sh)
to bring the primary back rather than promoting the Mac. Prefer this for short
outages; use full failover for longer ones.

## Encrypted backup (AS-17)
Separate from the live mirror, keep a periodic encrypted backup of the memory
workspace (and config, excluding secrets) to an external drive or owned storage.
Verify a restore actually works.

## Ticket map
- AS-3 epic: sync + failover (this runbook).
- AS-14: Syncthing mirror of the memory workspace.
- AS-15: exclude the SQLite index; rebuild from Markdown on failover.
- AS-16: failover runbook + a real drill (this doc, plus an actual stop-PC/start-Mac test).
- AS-17: encrypted backup of the workspace.
- AS-33: Wake-on-LAN (Mac wakes the PC).
- AS-12: iMessage channel (shared Mac bridge, per-host cliPath).
