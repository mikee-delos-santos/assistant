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
- iMessage identity is now OPTION B (2026-09-13): Messages on the Mac is signed in to
  a dedicated Apple ID for the assistant, with its own phone number. The Mac's macOS
  Apple Account is still Mark's. A test from Mark's iPhone reached the assistant number.
  The handles are private: see "Option B: identity switch" below.
- Assistant name / persona: NOT chosen yet (it becomes the iMessage contact name).

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
| 5 | PC + Mark | Test 1: Mark texts the assistant NUMBER from his iPhone. This is a real test now, because Mark's phone is a different Apple ID. Expect a reply from the assistant | TODO |
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
- SMS FORWARDING: the Mac's SMS account is still connected (Text Message Forwarding
  from Mark's iPhone). Turn it off on Mark's iPhone: Settings > Apps > Messages > Text
  Message Forwarding > MacBook Air = off. Otherwise the brain could read and send SMS as
  Mark.
- The PC Phase B notes above say "identity choice = Option A guarded test". That is
  replaced by this section. allowFrom now protects the assistant account, and Mark is a
  valid tester.

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
