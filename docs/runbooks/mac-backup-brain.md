# Mac onboarding from scratch: warm-backup brain + iMessage bridge

The Mac has NOT been set up for this project yet. This runbook takes it from zero to:
(a) on the Tailscale network, (b) able to run the OpenClaw brain as a warm backup to
the PC, and (c) hosting the free iMessage bridge so Mark and his wife can text the
assistant on whichever brain is active. The Windows PC is already the primary brain.

Covers AS-3 (epic) and AS-14, AS-15, AS-16, AS-17, AS-33, and ties into AS-12.

## Running this with Claude Code on the Mac
The Mac has Claude Code installed. You can open Claude Code on the Mac, tell it to
read this file (and Jira AS-3 / AS-16), and let it run the command-line steps.
Steps are tagged:
- [CLI] - a terminal command; Claude Code (or you) can run it.
- [GUI/You] - needs the GUI, a permission toggle, an app login, or an Apple ID
  sign-in; only you can do these. Claude should pause and ask you to do them.

## What you need on hand
- macOS 14 (Sonoma) or later. Check: `sw_vers` [CLI]
- Admin access on the Mac.
- The repo: https://github.com/mikee-delos-santos/assistant
- The SAME `ANTHROPIC_API_KEY` and `OPENCLAW_GATEWAY_TOKEN` used on the PC (from the
  PC's `.env`). You'll paste them into the Mac's own `.env`. Keep them handy.

---

## 1. Tailscale - join the tailnet  [GUI/You]
1. If Tailscale isn't installed: `brew install --cask tailscale` [CLI], or download
   from https://tailscale.com/download/mac
2. Open Tailscale and sign in with the SAME account as the PC and iPhone. [GUI/You]
3. Verify the PC is visible and note the Mac's own address:
   `tailscale status` (should list desktop-3p37btg / 100.123.4.5) and
   `tailscale ip -4` (the Mac's 100.x address). [CLI]

## 2. Homebrew  [CLI]
- If missing: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
- Verify: `brew --version`

## 3. Docker Desktop  [GUI/You]
1. Install: `brew install --cask docker` [CLI] (or https://www.docker.com/products/docker-desktop)
2. LAUNCH Docker Desktop and wait until it reports "running." [GUI/You]
3. Verify: `docker version` and `docker compose version` [CLI]

## 4. Clone the repo  [CLI]
```
mkdir -p ~/workspace && cd ~/workspace
git clone https://github.com/mikee-delos-santos/assistant
cd assistant
```
(If already cloned: `cd ~/workspace/assistant && git pull`.)

## 5. Create the Mac's .env (secrets - per-host, never synced, never committed)  [You]
```
cp .env.example .env
```
Edit `.env` and set `ANTHROPIC_API_KEY` and `OPENCLAW_GATEWAY_TOKEN` to the SAME
values as the PC. `.env` is gitignored; do not commit it and do not put it in the
Syncthing folder.

## 6. iMessage bridge (imsg)  [mix - follow imessage-mac-setup.md]
Do the steps in `docs/runbooks/imessage-mac-setup.md`:
- `brew install imsg` [CLI]
- Sign Messages into a DEDICATED free Apple ID = the assistant's identity (so it
  texts as itself, not as you). [GUI/You]
- Enable Remote Login: System Settings > General > Sharing > Remote Login = On. [GUI/You]
- Grant Full Disk Access + Automation to the terminal/imsg process. [GUI/You]
- Verify: `imsg chats --limit 1` lists a chat. [CLI]

## 7. Syncthing - mirror ONLY the Markdown memory  [mix]
1. Install and start: `brew install syncthing && brew services start syncthing` [CLI]
2. Open the Syncthing UI at http://127.0.0.1:8384 and pair with the PC's Syncthing
   (exchange device IDs). [GUI/You]
3. Share ONLY the PC's memory folder `data/openclaw/workspace` into the Mac at
   `~/workspace/assistant/data/openclaw/workspace`. Add `config/openclaw-home.stignore`
   as that folder's `.stignore` (excludes the SQLite index and logs). [GUI/You]
4. Verify memory files appear on the Mac and update within seconds when the PC changes
   them. [CLI: `ls ~/workspace/assistant/data/openclaw/workspace`]

Do NOT sync `.env` or `openclaw.json` - config and secrets stay per-host. That is
what lets the Mac wire iMessage to LOCAL imsg while the PC wires it to SSH-to-Mac.

## 8. STOP - do not start the container yet
The PC is the active brain. Starting the Mac container now = two brains writing the
same memory = split-brain. Leave the Mac container stopped until an actual failover.

## 9. Failover - promote the Mac to brain (only when the PC is down)  [CLI]
1. Confirm the PC gateway is actually stopped (avoid two brains).
2. `cd ~/workspace/assistant && docker compose up -d`
   (The SQLite index rebuilds from the synced Markdown on first start. The Mac's
   local imsg means iMessage keeps working.)
3. Point the Mac's iMessage cliPath at LOCAL imsg (not SSH). Claude can set it:
   `docker compose exec -T openclaw openclaw config set channels.imessage.cliPath <local-imsg-path>`
   (confirm the exact key/path against https://docs.openclaw.ai/channels/imessage).
4. Reach it over Tailscale (Control UI / `tailscale serve`) or
   `docker exec -it openclaw openclaw chat`.
5. When the PC returns: `docker compose stop openclaw` on the Mac, let Syncthing
   reconcile, then start the PC brain again.

## 10. Prefer waking the PC over failing over (AS-33)  [CLI]
For short PC outages, wake it instead of promoting the Mac: `scripts/wake-pc.sh`
(fill in the PC's MAC address first; needs WoL enabled in the PC BIOS/NIC).

## 11. Encrypted backup (AS-17)  [mix]
Keep a periodic encrypted backup of the memory workspace (and config, excluding
secrets) to an external drive or owned storage. Verify a restore actually works.

---

## Cross-brain iMessage recap
One assistant Apple ID. The imsg bridge lives on the always-on Mac. The active brain
connects to it - the PC brain over SSH/Tailscale, the Mac brain locally. Family texts
the one assistant identity; whichever brain is up answers. Exactly one brain runs at
a time. Reminders and briefings (AS-34) go out over the same iMessage channel, from
the assistant's identity.

## Ticket map
AS-3 (epic), AS-14 (Syncthing mirror), AS-15 (SQLite exclude/rebuild), AS-16 (this
runbook + drill), AS-17 (encrypted backup), AS-33 (Wake-on-LAN), AS-12 (iMessage).
