# OpenClaw on the Windows PC (the brain)

Covers AS-9 (run in Docker), AS-11 (harden), AS-12 reach-over-Tailscale.

## Prerequisites

- Docker Desktop for Windows installed and running.
- Tailscale up on the PC. This PC is `desktop-3p37btg` at `100.123.4.5` on the tailnet.
- A dedicated, non-admin Windows user that owns the OpenClaw data (AS-11). Run
  Docker/OpenClaw as that user so a bad prompt can't reach your personal files.

## Run it

From the repo root on the PC:

1. `cp .env.example .env` and fill `OPENCLAW_GATEWAY_TOKEN` (and later `ANTHROPIC_API_KEY`).
2. Pin a real image tag in `docker-compose.yml` (do not ship `:latest`).
3. `docker compose up -d`
4. `docker compose exec openclaw openclaw onboard` and follow the prompts.

Data persists on the host under `./data/openclaw` (config `openclaw.json`, the
SQLite state DB, agent profiles, and the Markdown workspace). This is the folder
Syncthing mirrors to the Mac - see `config/openclaw-home.stignore`.

## Reach it from your phone (no open ports)

Keep the container bound to `127.0.0.1:18789` (as in the compose file) and publish
it privately to the tailnet with Tailscale Serve:

```
tailscale serve --bg 18789
```

Then it's reachable at `https://desktop-3p37btg.<your-tailnet>.ts.net/` from any of
your devices on the tailnet, and nothing is exposed on the LAN or the public
internet. Do NOT bind 18789 to `0.0.0.0`.

## Hardening checklist (AS-11)

- Run under the dedicated non-admin user; its home holds only the OpenClaw data.
- `.env` and `data/` are gitignored; keep `.env` out of any backup that leaves the PC.
- Enable only the channels/skills you actually use; disable the rest.
- Keep the image version pinned and update deliberately.

## Keep it always-on (pairs with AS-33 Wake-on-LAN)

- `restart: unless-stopped` brings the container back after Docker/host restarts.
- In Windows power settings, disable sleep/hibernate for the brain user.
- In BIOS set "restore on power loss" so the PC returns after an outage.
