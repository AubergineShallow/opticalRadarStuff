---
name: foxglove-addon
description: Work on the optional Foxglove/Flora live-streaming broadcaster — the double gate that keeps it inert, what it publishes, SDK gotchas (subprotocol name, messages vs schemas, entity lifetimes, fixed ray length), install requirements, and how to smoke-test with Flora.
---

# Foxglove / Flora Broadcaster (optional add-on)

`server/foxglove_broadcaster.py` mirrors the data `websocket_server.py` already
sends, as Foxglove-protocol streams, so Flora/Foxglove's built-in 3D, Map, and
Plot panels can visualize the system live **without touching NEW-UI-V2 or the
JSON WebSocket**. It is strictly additive and off by default.

## The double gate (both must open)

1. **Import gate**: `import foxglove` at module top in a try/except sets
   `_FG_AVAILABLE`. SDK absent ⇒ every method is an inert no-op. Base env has no
   sdk ⇒ system_test Phase 14's "enabled publish" check counts a SKIP-pass.
2. **Config gate**: `foxglove.enabled` (default **False**; env
   `OR_FOXGLOVE_ENABLED=true`, port via `OR_FOXGLOVE_PORT`, default 8765).
   Rationale (in `FoxgloveConfig` docstring): a future `pip install foxglove-sdk`
   must not silently open a second listening socket streaming camera/track data.

`FoxgloveBroadcaster.start()` returns without starting unless
`self.enabled and _FG_AVAILABLE`. Keep this pattern for any new optional add-on.

## Wiring (server_main.py)

Constructed unconditionally as `self.fg_server` (inert when gated off); additive
`self.fg_server.*` calls sit beside the `ws_server` call sites:

| Loop event | Call |
|---|---|
| per cluster per frame | `publish_scene(cluster_id, tracks, hot_voxels, rays)` |
| per frame node flush (`_flush_node_updates`) | `publish_node_update(node)` per node + `publish_node_location(node_id, lat, lon, alt)` (raw GPS for the Map panel) |
| ~1 Hz status (`_broadcast_system_status`) | `publish_system_status(status)` + `publish_clusters(clusters_update)` |

When adding a new broadcast to `ws_server`, decide explicitly whether to mirror
it here; if yes, add the sibling call.

## SDK gotchas (each cost real debugging time)

1. **Subprotocol is `foxglove.sdk.v1`**, NOT the web-documented
   `foxglove.websocket.v1`. Negotiated internally by `foxglove.start_server`;
   only matters when writing a raw client-side smoke test — a client requesting
   the wrong subprotocol gets rejected.
2. Import from **`foxglove.messages`** (SceneEntity, CubePrimitive, …);
   `foxglove.schemas` is deprecated.
3. The `Ray`-style line primitive has **no range/length field** — rays are drawn
   at fixed `_RAY_LENGTH_M = 150.0`.
4. **SceneUpdate entities persist by id** in Foxglove; there are no per-id
   deletes here. Instead every entity carries a short lifetime
   (`_ENTITY_LIFETIME_NS`, ~2 frame times ≈ 66 ms at 30 fps) so stale geometry
   expires between publishes. Lifetime is relative to the entity's Timestamp —
   keep `_now()` wall-clock-correct.
5. Installed/verified combo: `foxglove-sdk` 0.25.3 (cp310-abi3 wheel) works on
   Python 3.14.

## Install & enable

```bash
cd code && pip install -r requirements-foxglove.txt   # just foxglove-sdk (base deps stay in requirements.txt)
# scipy is ALSO required to run the server at all (tracker's Hungarian assignment)
OR_FOXGLOVE_ENABLED=true python run_server.py --headless
```
(PowerShell: `$env:OR_FOXGLOVE_ENABLED='true'; python run_server.py --headless`)

## Smoke test with Flora/Foxglove

1. Start server with the env flag + feed it the sim swarm
   (`run-and-debug-server`).
2. In Flora/Foxglove Desktop: Open connection → Foxglove WebSocket →
   `ws://localhost:8765`.
3. Expect: 3D panel shows track cubes + labels, voxel cubes, and 150 m ray lines
   per cluster scene topic; Map panel shows node locations; Plot can graph
   system-status fields.
4. No panels populate ⇒ check the two gates in order: server log at startup
   (import gate / disabled), then `netstat -an | findstr 8765` (socket open?).

## Validation

system_test Phase 14: the disabled-is-inert test ALWAYS runs (no sdk needed —
this is what protects mainline behavior); the enabled publish test runs only when
the sdk imports, else prints `SKIPPED (foxglove-sdk not installed)` and counts as
a pass. If you change the broadcaster, install the sdk locally so the enabled
path actually executes.

## Related skills

`run-and-debug-server` (the broadcasts being mirrored), `validate-changes`
(Phase 14 semantics), `quality-standards` (the opt-in add-on pattern).
