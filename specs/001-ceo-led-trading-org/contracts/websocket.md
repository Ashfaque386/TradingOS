# Contract — Live Console WebSocket

**Feature**: CEO-Led AI Trading Organization | **Date**: 2026-09-10

Extends the existing WebSocket relay (`src/api/routers/streams.py`, which already serves `/stream/market/{symbol}`, `/stream/agents/logs`, `/stream/portfolio`). Reuses the same auth, the same `requestAnimationFrame`/throttled client hooks pattern, and the same "stream is a hint, REST is the truth" philosophy.

## Endpoint

`WS /api/v1/stream/organization`

- **Auth**: same JWT check as the other stream endpoints; any authenticated role may subscribe (read-only). No role may mutate over the socket.
- **Subscription message** (client → server, once after connect):
  ```json
  { "subscribe": { "run_ids": ["uuid", "..."] } }   // omit or [] for "all active runs"
  ```
  The client may send further `subscribe` messages to change the filter without reconnecting.
- **Server → client frames**: the `OrganizationalEvent` envelope from `contracts/events.md`, relayed from the Redis `organization:events` channel, filtered to the subscribed `run_ids`. Additionally a periodic `{"heartbeat": "<iso8601>"}` (matches the existing streams).

## Client behaviour (FR-088, FR-172, R15)

- **One** multiplexed subscription per open console session (keyed by the selected run set) — never one-per-panel (FR-172, no duplicate subscriptions).
- On receiving an event, patch the React Query cache for the affected run/task/approval; do **not** refetch the whole run on every event.
- On reconnect (disconnect handled gracefully): resubscribe with the same `run_ids`, then call `GET /organization/runs/{id}/events?after_sequence=<last seen>` per subscribed run to backfill any missed events, then resume patching. No full page reload; selected run/agent context preserved (FR-090, spec edge case "Live channel disconnect").
- Respect `prefers-reduced-motion`: state-change animations (running pulse, dependency-edge activation, hand-off transition) degrade to instant state swaps (FR-170).
- Large event lists in the activity stream are windowed/virtualised (FR-172).

## What the socket does NOT do

- No approval, config, pause/resume, or any mutation — those are REST only (contracts/rest-api.md), so RBAC is enforced in one place.
- No private model reasoning in any frame (FR-023).
- No simulated/heartbeat-only "activity" — every non-heartbeat frame corresponds to a real `organizational_events` row (FR-081, FR-089, constitution VI).
