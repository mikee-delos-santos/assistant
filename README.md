# Assistant

Personal voice assistant ("Jarvis"), built by adopting [OpenClaw](https://openclaw.ai/) and adding a voice PWA, hardening, custom skills, and deep integration with the Chores app.

Planned and tracked in Jira project **AS** (board 68): https://markrdelossantos.atlassian.net/jira/software/projects/AS/boards/68

## Architecture (short version)

- **Brain:** Windows PC, always on, OpenClaw in Docker, Claude API as the model.
- **Backup brain:** Mac (~98% on), warm standby. Syncthing mirrors the Markdown workspace; exactly one brain runs at a time; the Mac can Wake-on-LAN the PC.
- **Access:** phone + PC are clients over a Tailscale tailnet (no port forwarding, beats CGNAT).
- **Data:** lives only on the two machines. No rented cloud for personal data.
- **Family channel:** iMessage via a BlueBubbles bridge on the Mac.
- **Chores:** integrated through the app's existing MCP server (`POST /mcp` on chores.mikeedelossantos.dev).

## Working rules (Jira -> git centered)

- One branch per ticket, named `AS-<n>-short-desc` (e.g. `AS-6-tailscale-setup`).
- Commit subjects start with the ticket: `AS-<n> — short description`.
- Never put ticket IDs in code comments; they belong only in the branch name and commit subject.
- Update the ticket at the end of every work session: move its status and leave a comment on what was done and what's next.

## Layout

- `docs/runbooks/` — setup and operational runbooks, one per area.
- `docs/decisions/` — short decision records where a choice needs a paper trail.
