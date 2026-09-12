# iMessage channel (free) via imsg over Tailscale

Goal: let the family text the assistant over iMessage at $0, using the Mac as the
Apple bridge while the brain stays on the Windows PC. Covers AS-12.

## Why it's free
iMessage, the `imsg` CLI (Homebrew), Tailscale, and SSH are all free. No Twilio,
no BlueBubbles server, no paid API. The only cost is the Mac being on.

## Architecture
- Brain / gateway: Windows PC (OpenClaw in Docker) - already running.
- iMessage bridge: Mac (Messages.app + the `imsg` CLI).
- Link: the PC gateway calls `imsg` on the Mac over Tailscale via SSH; attachments come back via SCP.
- The Mac is the "Apple bridge" for both iMessage and Apple Reminders (AS-35).

## Prerequisites
- Mac on macOS 14+ and on the tailnet (Tailscale installed and signed in).
- Messages signed into an Apple ID. The prototype uses Mark's personal Apple ID
  (Option A, see ROADMAP.md). For real family use, a dedicated FREE Apple ID
  (Option B), so it shows up as its own contact instead of replying "as you."
- PC and Mac on the same tailnet (already true: PC is desktop-3p37btg / 100.123.4.5).

## Mac-side setup (do this at the Mac)
1. Install Homebrew if needed:
   `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
2. Install the imsg CLI: `brew install steipete/tap/imsg`
   (If the formula name differs, check the current tap at https://docs.openclaw.ai/channels/imessage)
3. Sign Messages into the Apple ID: personal for the prototype (Option A), dedicated
   later (Option B).
4. Enable Remote Login so the PC can SSH in over Tailscale:
   System Settings > General > Sharing > Remote Login = On.
   Note the Mac's tailnet IP: `tailscale ip -4`
5. Grant permissions in System Settings > Privacy & Security:
   - Full Disk Access: add Terminal (and the shell/process that runs imsg) so it can
     read `~/Library/Messages/chat.db`.
   - Automation: allow Terminal / imsg to control Messages.app (to send).
6. Verify on the Mac: `imsg chats --limit 1` should list a chat.
   If it errors on permissions, re-check Full Disk Access and re-run.

## PC-side setup (Claude handles this once the Mac side verifies)
Current step-by-step plan: ROADMAP.md, section "Handoff: wire the PC brain to imsg
over SSH". Scripts: `scripts/imsg-ssh-gate.py` (Mac forced command) and
`scripts/imsg-over-ssh.sh` (brain-side cliPath wrapper).

1. Passwordless SSH from PC to Mac: generate a key on the PC, add the public key to
   the Mac's `~/.ssh/authorized_keys`. Test: `ssh <mac-user>@<mac-tailnet-ip> /opt/homebrew/bin/imsg chats --limit 1`
   (full path, because a non-interactive SSH command does not load the Homebrew PATH).
   SSH sessions also need Full Disk Access for /usr/libexec/sshd-keygen-wrapper.
2. Wrapper script the gateway calls as `cliPath` that runs `imsg` on the Mac via SSH
   (and `scp` for attachments).
3. Configure OpenClaw: set `channels.imessage.cliPath` to the wrapper, set
   `channels.imessage.dbPath` if required, and enable the imessage channel.
4. Restart the gateway; confirm with `openclaw channels list`.
5. Route replies to iMessage; test by texting from a DIFFERENT Apple ID
   (e.g. Mark's wife's phone). Under Option A, a text from Mark's own iPhone is Mark to
   himself and does not test the bridge.

## Known catches (still $0)
- Use a dedicated free Apple ID so the assistant isn't "you."
- Fragile across macOS updates/reboots: Full Disk Access and permissions can reset -
  re-grant if it stops working (the well-known "reboot that breaks it").
- Apple gray area: automating Messages is not Apple-sanctioned. Fine with Anthropic
  and free; keep it to personal/family scale.
- Full Disk Access is powerful - the bridge can read all Messages history. Keep it on
  a machine you control (the Mac).

## References
- https://docs.openclaw.ai/channels/imessage
- https://docs.openclaw.ai/gateway/remote
- Remote Mac over Tailscale pattern: https://www.alibabacloud.com/help/en/simple-application-server/use-cases/invoking-imessage-via-openclaw
