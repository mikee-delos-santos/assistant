# ADR 0001: Personal assistant architecture

Status: accepted (brainstormed 2026-08-30). Tracked in Jira project AS.

## Context

Mark wants a voice-driven personal assistant ("Jarvis") that remembers things,
holds work/family context, runs on his always-on home machines, and is reachable
from his phone. He is in the Philippines (CGNAT, no reliable port forwarding),
English is his second language, and he already runs a Chores app with an MCP server.

## Decisions

1. Adopt OpenClaw rather than build from scratch. It already provides the brain,
   persistent memory, channels, and a skill system. We build a voice PWA, hardening,
   custom skills, and Chores integration on top.
2. Brain runs on the Windows PC (beefier, most-on) in Docker; the Mac is a warm
   backup that runs the same image only when promoted. Exactly one brain at a time.
3. Cloud Claude API as the model for quality. Accepted tradeoff: message context
   leaves the machine to Anthropic per turn. A local model on the PC is the future
   path to zero egress.
4. Access over a Tailscale tailnet (WireGuard). Beats CGNAT with no port forwarding
   and no public exposure. Publish the gateway with Tailscale Serve, not open ports.
5. Data lives only on Mark's two machines. No rented cloud (incl. Railway) for PII.
6. Memory syncs via Syncthing (peer-to-peer, free). Markdown is the source of truth
   and syncs; the derived SQLite index is excluded and rebuilt on failover.
7. Family channel is iMessage via a BlueBubbles bridge on the Mac (Mac ~98% on).
   The PWA remains Mark's primary channel.
8. Voice uses a cascade pipeline (STT -> LLM -> TTS) with accent-robust server-side
   STT and a visible, correctable transcript. Not speech-to-speech.
9. Chores integration reuses the app's existing MCP server; no new backend.

## Consequences

- Security surface is real: OpenClaw has shell/file access and stores PII in
  plaintext. Mitigations: dedicated non-admin user, full-disk encryption (deferred
  on the PC, AS-7), locked-down secrets, Tailscale-only access.
- Failover needs the one-brain-at-a-time discipline to avoid split-brain writes.
- Wake-on-LAN (Mac wakes PC) is the only remote-wake fallback (AS-33).
