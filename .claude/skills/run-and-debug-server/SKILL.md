---
name: run-and-debug-server
description: Start, configure, and debug the OpticalRadar Python server — config file and OR_* env overrides, ports, feeding it simulated or real telemetry, tracing a packet through the ingest pipeline, and diagnosing why telemetry is silently dropped or tracks never appear.
---

# Run and Debug the Server

All commands run from the `code\` directory of the project root.

## Quick start

```bash
# Git Bash
cd code && python run_server.py --headless
```
```powershell
# PowerShell
cd code; python run_server.py --headless
```

- `run_server.py` is a thin launcher that adds `code\` to `sys.path` and calls
  `server/server_main.py::main`. Equivalent: `python -m server.server_main`.
- Flags (see `server_main.py::main`): `--config <path>` (default `config.yaml`;
  **defaults are used if the file is absent** — a missing config is not an error) and
  `--headless` (skip the local `server/visualizer.py` window; always use this in
  agent/CI sessions).
- Expected startup log lines (structured logger, also appended to `logs/sys.log`):
  `Initializing OpticalRadar server`, a security enabled/disabled line, then
  `OpticalRadar server started successfully`.
- Stop with Ctrl+C (SIGINT handler calls `OpticalRadarServer.stop()`).

## Configuration

`common/config.py` defines dataclass sections composed into `Config`, loaded by
`load(path)`: YAML file first (unknown keys warn and are dropped —
`_build_section`), then env overrides (`_apply_env_overrides`).

**Env override pattern: `OR_<SECTION>_<PARAM>`** — section is the FIRST token after
`OR_`, the rest is the param, case-insensitive. So `OR_NETWORK_UDP_PORT=6000` sets
`network.udp_port`; `OR_SERVER_WS_PORT=5001` sets `server.ws_port`. Booleans accept
`true/1/yes`. Malformed values (e.g. `OR_NETWORK_UDP_PORT=abc`) print a warning and
keep the default — they never abort startup.

Key sections and defaults (from `common/config.py` — the file is short, read it for
the full list):

| Section.param | Default | Meaning |
|---|---|---|
| `network.udp_port` | 5005 | V3 telemetry/announce UDP ingest |
| `network.max_packet_size` | 65535 | recvfrom size (512 used to truncate dense packets) |
| `network.max_nodes` | 256 | node-registry cap (announce-flood guard) |
| `network.max_clusters` | 64 | cluster cap (each = full grid+tracker) |
| `network.max_vectors_per_packet` | 512 | per-datagram ray-build cap |
| `server.ws_port` | 5000 | WebSocket for NEW-UI-V2 (**must match frontend Env.WS_URL**) |
| `server.target_fps` | 30 | main loop rate |
| `reference.origin_lat/lon/alt` | 37.7749 / -122.4194 / 0.0 | ENU origin; **must match `NEW-UI-V2/constants.ts` COORDINATE_ORIGIN** |
| `security.enabled` | False | HMAC verification (see `security-provisioning` skill) |
| `security.key_file` | `secrets/shared.key` | server key file |
| `monitoring.prometheus_port` | 8000 | metrics HTTP exporter |
| `monitoring.log_file` | `logs/sys.log` | structured log destination |
| `grid.*`, `tracking.*`, `calibration.*` | — | see `tracking-fusion` skill |
| `foxglove.enabled/port` | False / 8765 | see `foxglove-addon` skill |
| `lora.*` | disabled | see `lora-meshtastic` skill |

Special case: `OR_SECURITY_ENABLED` is read **directly** in
`server_main.py::__init__` and can force security on OR off regardless of config
(`0/false/no/off` and `1/true/yes/on` are both honoured).

## Ports

| Port | Default | Protocol | Config |
|---|---|---|---|
| UDP telemetry | 5005 | custom binary V3 | `network.udp_port` |
| WebSocket UI | 5000 | JSON messages | `server.ws_port` |
| Prometheus | 8000 | HTTP text | `monitoring.prometheus_port` (off via `monitoring.metrics_enabled=false`) |
| Foxglove | 8765 | foxglove.sdk.v1 WS | `foxglove.port` (opt-in) |
| LoRa-over-UDP | 5006 | LoRa wire format | `lora.udp_port` (opt-in, NOT the V3 port) |

## Startup failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError: Authentication initialization failed` (log: "security.enabled is set but no keys could be loaded") | `security.enabled` true but key file missing/empty. **Deliberate fail-fast** — an empty-key Authenticator would silently drop 100% of traffic (BUG-008 history). | `python provision_node.py generate` or disable: `OR_SECURITY_ENABLED=false`. |
| `OSError` on UDP bind | Port 5005 in use (another server instance, or a test suite run) | Kill the other process or set `OR_NETWORK_UDP_PORT`. Note `UDPServer.start()` sets SO_REUSEADDR, so a stale TIME_WAIT socket is not the cause. |
| LoRa gateway error in log but server keeps running | `lora.enabled` with no radio attached. By design non-fatal: `start()` catches it, logs `LoRa gateway failed to start`, sets `lora_server=None`; UDP path unaffected. | Attach radio or disable `lora.enabled`. |
| Visualizer/window errors | Running without a display | Use `--headless`. |

## Feeding it data (no hardware needed)

The simulation is a **library**, not a CLI. Recommended smoke recipe — server in one
terminal, then run a 4-camera / 2-target swarm for 30 s (from `code\`):

```bash
PYTHONUTF8=1 python -c "
import threading
from simulation.sim_node import create_demo_simulation
nodes = create_demo_simulation(num_cameras=4, num_targets=2)
ts = [threading.Thread(target=n.run, kwargs={'duration': 30.0}) for n in nodes]
[t.start() for t in ts]; [t.join() for t in ts]
"
```
```powershell
# PowerShell: write the snippet to a temp file (one-liners with embedded
# newlines are fragile in PS 5.1), then run it:
@'
import threading
from simulation.sim_node import create_demo_simulation
nodes = create_demo_simulation(num_cameras=4, num_targets=2)
ts = [threading.Thread(target=n.run, kwargs={'duration': 30.0}) for n in nodes]
[t.start() for t in ts]; [t.join() for t in ts]
'@ | Out-File -Encoding ascii $env:TEMP\run_sim.py; $env:PYTHONUTF8='1'; python $env:TEMP\run_sim.py
```

Facts that matter (verified in `simulation/sim_node.py`):
- `SimNode` defaults to sending to `127.0.0.1:5005`.
- `create_demo_simulation` places cameras in a circle and — critically — generates
  ONE shared target set for all cameras (per-camera random targets would make
  multi-camera triangulation impossible; that was a real bug once).
- `SimNode.start()` sends an ANNOUNCE (and re-announces every 5 s in `run()`).
  Without an announce the server parks the node in the pending pool and telemetry
  is **never processed** — see silent-drop checklist below.
- Camera GPS coords come from a proper `enu_to_wgs84` inverse using the same origin
  as `ReferenceConfig` (37.7749, -122.4194) — do not "simplify" this.

Other sources: `esp32/esp32_stub.py` (has a `__main__`, emits real V3 telemetry) and
real nodes (`edge-nodes` skill). The UI's mock mode (`?mock=true`) is
frontend-internal and never touches the server.

## The ingest pipeline (trace a packet)

Stage order, with the exact symbols to instrument or breakpoint:

1. `server/udp_server.py::UDPServer._receive_loop` (daemon thread) — recvfrom,
   peeks byte[1] for packet type, `AnnouncePacket.unpack` or
   `TelemetryPacket.unpack`, queues a `ReceivedPacket`. Malformed bytes are
   dropped **silently** (parse failure returns None). Queue is bounded (1000);
   overflow increments `_packets_dropped` (see `get_stats()`).
2. `server/server_main.py::_run_loop` — drains `udp_server.get_packets()` (≤100 per
   frame) and, if enabled, `lora_server.get_packets()` (those are `trusted=True`,
   skipping HMAC — the LoRa link is physically scoped and carries no signature).
3. `_process_packet(packet, address, trusted)` — the gauntlet, in order:
   a. **HMAC gate** (only if authenticator active and not trusted):
      `authenticator.verify_signed_packet` — failure logs
      `Signature verification failed` and drops.
   b. Type routing: ground truth → `_process_ground_truth_packet`; announce →
      `_process_announce_packet` (registers optics, auto-assigns to DEFAULT
      cluster, subject to `max_nodes` cap); unknown type → warn+drop.
   c. **Sanity gate** `_telemetry_sane`: non-finite lat/lon/alt/timestamp,
      |lat|>90, |lon|>180, non-finite or near-zero quaternion → logs
      `Dropping malformed telemetry` and drops.
   d. `health_monitor.record_packet` (always happens for sane telemetry).
   e. **Cluster routing**: `cluster_manager.get_cluster_for_node` — a node that
      never announced is pending ⇒ **silent return, no log**.
   f. **GPS gate**: rays are built only if `packet.health_flags & 0x01` (GPS fix
      bit). Without it, node status still updates but zero rays are built.
   g. **Vector cap**: >512 vectors logs a warning and truncates.
   h. `cluster.ray_builder.build_rays_from_packet(...)` → rays →
      `cluster.voxel_grid.add_rays_batch(rays, frame_index)`.
4. Back in `_run_loop`, per cluster per frame: `voxel_grid.decay_active_leaves()`,
   throttled `consolidate_and_prune()` (every ≥1.5 s), `voxel_grid.get_detections()`
   → `_build_detections` (attaches covariance from `server/uncertainty.py` and a
   physical-size sample — see `tracking-fusion` skill) → `cluster.tracker.update()`.
5. Broadcast: `_broadcast_tracks` (`TRACK_UPDATE`, room = cluster_id),
   `_broadcast_voxels` (`VOXEL_UPDATE`, capped 256), `_broadcast_rays`
   (`RAY_UPDATE`, capped 256), batched `NODE_UPDATE` once per frame
   (`_flush_node_updates`), `SYSTEM_STATUS` + `CLUSTER_UPDATE` ~1/s. Message
   envelope: `{"type": ..., "timestamp": ..., "payload": ...}` from
   `websocket_server.py::broadcast`.

## Silent-drop checklist ("server runs, no tracks")

Work top to bottom; each row names the observable that proves/rules it out.

| # | Cause | How to confirm |
|---|---|---|
| 1 | Security on, nodes unsigned | Log shows `Signature verification failed`. Check `OR_SECURITY_ENABLED` / config. |
| 2 | Node never announced → pending pool | `SYSTEM_STATUS.pending_nodes` (WS) lists it; `_process_packet` returns at cluster routing with **no log**. Fix: node must send ANNOUNCE (or `ASSIGN_NODE` a known node). |
| 3 | GPS health bit unset (`health_flags & 0x01 == 0`) | Node shows in UI but no rays; check `health_flags` in NODE_UPDATE. Common with real GPS indoors / cold start. |
| 4 | Malformed telemetry (NaN, zero quaternion) | `Dropping malformed telemetry` in log. |
| 5 | Wrong ENU origin | Nodes' `location` in NODE_UPDATE is thousands of km out, or all rays miss the 200×200×100 m grid. `reference.*` must match node GPS *and* frontend `COORDINATE_ORIGIN`. |
| 6 | Rays built but no hot voxels | Single camera only (needs multi-camera co-temporal subdivision to concentrate heat) or `grid.hot_threshold` too high. See `tracking-fusion`. |
| 7 | Detections but tracks not confirmed | `tracking.min_hits_to_confirm` (3) not yet reached, or association gate too tight. |
| 8 | UDP queue overflow | `udp_server.get_stats()['packets_dropped']` > 0. |
| 9 | Wrong port / firewall | `netstat -an \| findstr 5005` (PowerShell) shows the listener; Windows Firewall prompt may have been declined. |

## Monitoring

- **Logs**: `StructuredLogger` writes `logs/sys.log` (config `monitoring.log_file`)
  and console. Level via `monitoring.log_level`.
- **Prometheus**: `server/monitoring/metrics.py::MetricsCollector.start_http_exporter`
  serves `http://localhost:8000/metrics` when `monitoring.metrics_enabled` (default
  true). Key metrics: packets processed counter, active-tracks gauge per cluster,
  per-frame processing-time histogram, calibration score. A `snapshot()` is also
  folded into every `SYSTEM_STATUS` broadcast.
- **Node health**: `server/monitoring/node_health.py::NodeHealthMonitor` derives
  HEALTHY/DEGRADED/UNHEALTHY/OFFLINE from packet recency, sequence gaps and health
  flags; surfaced per node in the UI SensorList.

## Debugging tips

- One frame at a time in a REPL: construct `OpticalRadarServer(headless=True)`,
  don't call `start()`; feed packets with `server._process_packet(pkt, ('127.0.0.1', 0))`
  and tick with `server.process_frame()` (the legacy test helper). This is exactly
  how `system_test.py` drives it — see `validate-changes` skill.
- `server.start()` binds real sockets — a past bug class lived only in `start()`
  (BUG-007: UDPServer was handed a Config object as the port). There is a
  regression test for this; don't test only via `_process_packet`.
- WS commands from the UI are untrusted input: `CREATE_CLUSTER` (cap 64) and
  `ASSIGN_NODE` (known nodes only) are deliberately restrictive — see
  `quality-standards` skill before "fixing" a refused command.
