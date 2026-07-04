---
name: quality-standards
description: The engineering bar for OpticalRadar changes — hardening patterns (every collection bounded, fail-fast vs graceful degradation), the review checklist derived from this project's actual bug history, the deferred-architecture register with current status, known architectural tensions, and the multi-agent review workflow to reuse for large changes.
---

# Quality Standards (the bar to hold)

This project's history: it "worked" and passed its tests while carrying
ship-blocking bugs — silent packet drops, unbounded memory growth, wire-format
mismatches the UI read as zeros. The standards below each trace to a real shipped
bug. Hold the line.

## Hardening patterns (verified in code 2026-07-03)

**Rule 1 — every unbounded thing gets a cap, with a config default.** Current
inventory (know these before adding a new collection or loop):

| Guard | Where | Default |
|---|---|---|
| node registry cap (announce floods) | `server_main._process_announce_packet` + `network.max_nodes` — rejection is **side-effect-free** (a rejected announce must not leak into pending_nodes) | 256 |
| cluster cap (each = grid+tracker) | `ClusterManager.create_cluster` returns None at `network.max_clusters`; DEFAULT always fits | 64 |
| per-datagram vector cap | `server_main._process_packet` + `network.max_vectors_per_packet` | 512 |
| octree leaf ceiling (THE perf guard) | `VoxelGridConfig.max_active_leaves` — at cap, deposit into coarse leaf, degrade gracefully | 20000 |
| UDP packet queue | `UDPServer` Queue(maxsize=1000), drops counted | 1000 |
| LoRa gateway queue | `LoRaGateway._ingest` | 1000 |
| LoRa framer | `max_payload` (false-sync guard) + `max_buffer` | 64 / 4096 |
| WS rooms | `subscribe` moves clients (one room per client) + `unsubscribe` prunes empties ⇒ `_rooms` ≤ client count | — |
| replay filter FIFO | `Authenticator._seen_order` deque | 8192 |
| broadcast payloads | voxels/rays sliced `[:256]` per frame in `server_main` | 256 |
| UI trails | `store.ts MAX_TRAIL_POINTS`, pruned for vanished tracks | 60 |

**Rule 2 — fail fast on misconfiguration, degrade gracefully on load.**
Misconfig that would cause silent wrong behavior must halt with instructions
(security-on-without-keys RuntimeError; `make_transport` raises on a serial
transport without a device — the edge node halts; the server deliberately
catches gateway-construction errors, logs, and stays UDP-only).
Resource pressure must degrade, not die (octree cap, queue drops with counters,
LoRa radio failure leaving UDP alive). Never invert these.

**Rule 3 — no silent drops without a counter or log.** Every drop path either
logs (`Dropping malformed telemetry`, signature failures, vector-cap warnings) or
counts (`packets_dropped`, `orphan_updates`, `queue_dropped`). The one deliberate
exception — unassigned-node telemetry — is visible via `pending_nodes` in
SYSTEM_STATUS. If you add a drop path, add its observable.

**Rule 4 — untrusted input is validated at the boundary.** UDP: parse-failure
drop, `_telemetry_sane` (NaN/Inf/zero-quaternion/range checks). WS: non-dict
JSON frames and non-dict payloads ignored (`_on_message`); `CREATE_CLUSTER`/
`ASSIGN_NODE` validated + capped; room keys must be non-empty strings. Anything
a client controls gets the same treatment.

**Rule 5 — opt-in add-ons must be double-gated** (config flag AND import guard)
so a `pip install` can never silently activate a network service. Pattern:
`foxglove-addon`.

**Rule 6 — bug fixes ship with the regression check that would have caught
them** (see system_test Phase 12's origin story in `validate-changes`).

## Review checklist (from this codebase's actual bug classes)

When reviewing any change, hunt these specifically:

1. **Wire/UI key mismatches** — server payload keys vs `types.ts`/UI readers
   (BUG-011: status dashboard read undefined and showed zeros; a separate
   since-fixed bug sent NODE_UPDATE status as the string "active", which never
   matched the UI's numeric enum, so every node rendered red).
2. **API calls that don't exist** — past bugs called `process_ground_truth()`,
   `get_metrics()`, `hit_count` on objects that never had them; some only crash
   at runtime on a rarely-exercised path. Verify attribute names against the
   defining class, especially across module boundaries.
3. **Constructor argument mismatches** — BUG-007 passed a Config object as a
   port int; crashed only in `start()`, which tests never called.
4. **Units/frames** — degrees vs radians, [w,x,y,z] order, ENU origin agreement,
   truncate-vs-round (see `geometry-conventions`, `wire-protocols`).
5. **Unbounded growth** — new dict/list/set keyed by anything client-derived
   needs a bound (Rule 1) — this includes the UI store.
6. **Silent failure** — new early-return needs a log/counter (Rule 3).
7. **Dead config knobs** — a knob added to `common/config.py` must be consumed;
   `monitoring.prometheus_port` and `grid.hot_threshold` were once silently
   ignored. Grep for the consumer.
8. **Hot-loop cost** — anything added to `_run_loop`/`_process_packet` runs up
   to 30×/frame×packets; the size-estimation O(det×rays) regression (stress S8)
   is the standing example.
9. **Test blind spots** — does the change only work because tests use
   headless/authenticator=None/FakeConfig? (`validate-changes` blind-spots list.)

## Deferred-architecture register (status verified 2026-07-03)

Deferred BY USER DECISION 2026-07-02 — do not "helpfully" fix these in an
unrelated PR; do reference this list when one blocks you:

| Item | Status | Notes |
|---|---|---|
| Packaging (pyproject) to kill `sys.path.insert` hacks | still deferred | 10+ files carry the hack; it works; churn is high |
| Move calibration solve + broadcast JSON serialization off the 30 Hz loop thread | still deferred | solve every 10 s can stutter a frame; serialization cost scales with clients |
| Unify the two `ReceivedPacket` dataclasses (`udp_server` / `lora_gateway`) | still deferred | deliberately mirrored; unify only with a shared module, not an import cycle |
| Validated config schema | still deferred | `_build_section` warns+drops unknown keys — typos are survivable but only warned |
| Server-side consumption of angular_size | **DONE 2026-07-03** | physical-size estimation; see `tracking-fusion` |

## Known architectural tension (roadmap-grade)

LoRa UPDATEs are translated to single-bearing telemetry, so a LoRa node
participates in octree consensus only as one camera among
`min_cameras_to_subdivide` (3) — pre-filtered "mature tracks" at low cadence are
structurally weak inputs to the multi-camera co-temporal subdivision trigger.
`Discussion.txt` (historical review) proposes frustum/volumetric ingestion using
the angular_size field as the unifying fix. Nothing implemented; treat as design
input, not gospel, if fusion of LoRa-heavy deployments becomes a priority.

## Multi-agent review workflow (for large changes)

The pattern that produced the 2026-07 rounds, reusable by any session:

1. **Ground truth first**: run both suites (`validate-changes`) before touching
   anything; record the summary lines.
2. **Author** the change with the checklist above in hand.
3. **Adversarial cross-review**: a SEPARATE agent/session (not the author)
   verifies every claim/path/symbol in the diff against the code, hunting
   checklist classes 1–9 specifically; findings fixed, not argued with.
4. **Re-test** both suites + UI verification when touched; new checks for new
   behavior.
5. **Record**: update the relevant skill(s) under `.claude/skills/` when a
   convention, cap, or gotcha changes — the skills are part of the codebase.

Historical review artifacts (`Code_Review.md`,
`lumped_source_code_v2-AUDIT_RESULTS/`) show the standard: 34/34 audit claims
validated against source with code evidence before any fix landed. Findings in
them are point-in-time — several are already fixed; re-verify before acting
(`edge-nodes` shows the discipline).

## Related skills

`validate-changes` (definition of done), `run-and-debug-server` (observables for
Rule 3), every domain skill for its local conventions.
