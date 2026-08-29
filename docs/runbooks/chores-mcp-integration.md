# Chores app integration via MCP

Covers AS-26 and its stories. Wires the brain into the existing Chores app
(chores.mikeedelossantos.dev), which already ships an MCP server (PC-70).

## What already exists (no backend work needed)

- Endpoint: `POST https://chores.mikeedelossantos.dev/mcp`
  (Streamable HTTP, tools-only, plain JSON, no SSE).
- Auth: `Authorization: Bearer <admin JWT>`, scoped to the family. An admin JWT
  is effectively full family admin; there is no per-agent revocation in v1.
- Tools (6): `create_chore`, `approve_chore`, `reject_chore`, `list_chores`,
  `list_children`, `post_chore_from_template`.

## Wire it into OpenClaw (AS-27)

Merge `config/openclaw.mcp.chore-app.json` into `~/.openclaw/openclaw.json` under
`mcpServers`, then restart the gateway. The token comes from the environment, not
the file:

```
"mcpServers": {
  "chore-app": {
    "transport": "streamable-http",
    "url": "https://chores.mikeedelossantos.dev/mcp",
    "headers": { "Authorization": "Bearer ${CHORES_MCP_TOKEN}" }
  }
}
```

Set `CHORES_MCP_TOKEN` in `.env` (AS-28). Verify with the MCP handshake: the
gateway should list the six tools after restart.

## Secret handling (AS-28)

- Store the JWT only in `.env` on the brain host. Never in synced Markdown or backups.
- Since it is full admin, document how to rotate/revoke it if the host is compromised.

## Voice behaviour (AS-29..AS-31)

- Read tools (`list_children`, `list_chores`) are safe - ship first to prove the pipe.
- `create_chore` / `post_chore_from_template`: read back what will be created first.
- `approve_chore` moves coins and `reject_chore` is terminal - require an explicit
  spoken confirmation before firing, and speak the app's errors (non-open chore,
  not found) back plainly.
