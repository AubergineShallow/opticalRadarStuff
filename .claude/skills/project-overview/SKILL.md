---
name: project-overview
description: Orientation for the PassiveOpticalTracking (OpticalRadar) project — system architecture and data flow, directory map, entry points, what can and cannot be built locally, provenance of the tree, and a routing table to the other eleven skills. Read this first when starting any task in this repository.
---

# Project Overview — OpticalRadar / PassiveOpticalTracking

A **passive optical tracking system**: distributed camera nodes detect moving
objects and stream **bearing-only** telemetry (azimuth/elevation — no range) to
a central Python server, which fuses bearings from multiple viewpoints into 3D
tracks and broadcasts them to a browser UI.

## Data flow

```
 EDGE NODES                      TRANSPORT           SERVER (code/server, 30 Hz loop)                 CLIENTS
┌──────────────────┐                                ┌──────────────────────────────────────┐
│ rpi/rpi_node.py  │──V3 UDP:5005──────────────────▶│ udp_server ─┐                        │
│ android_node/    │──V3 UDP:5005──────────────────▶│             ├─▶ _process_packet      │
│ esp32/firmware   │──V3 UDP / LoRa────────────────▶│ lora_gateway┘   (auth → sanity →     │   ┌──────────────────┐
│ esp32_stub.py    │──V3 UDP:5005──────────────────▶│                  cluster route →     │──▶│ NEW-UI-V2        │
│ sim_node.py      │──V3 UDP:5005──────────────────▶│                  GPS gate)           │WS │ React + deck.gl  │
│ rpi/lora_node.py │──LoRa (Meshtastic/serial/udp)─▶│   ray_builder → voxel_grid (octree)  │5000│ ws://…:5000/ws  │
└──────────────────┘                                │   → tracker (Kalman) → broadcasts    │   └──────────────────┘
                                                    │   + calibration loop + size estimate │──▶ Foxglove/Flora :8765 (opt-in)
                                                    └──────────────────────────────────────┘──▶ Prometheus :8000/metrics
```

Key idea: one camera gives a bearing ray; the sparse octree voxel grid
accumulates ray "heat" and only subdivides where **≥3 distinct cameras** agree
within a co-temporal window — that intersection IS the triangulation. Hot voxel
centroids become detections; a Kalman tracker with optics-derived per-measurement
covariance turns them into tracks.

## Directory map

```
code\
  run_server.py            launcher → server.server_main.main()
  system_test.py           functional suite (17 phases; see validate-changes)
  stress_test.py           adversarial suite (S1–S14)
  provision_node.py        HMAC key CLI (generate/rotate/show/distribute)
  requirements*.txt        base / -lora / -foxglove extras
  LORA_SETUP.md            human LoRa/Meshtastic setup guide
  common\                  config (dataclasses + OR_* env), protocol.py (V3 wire),
                           lora_protocol.py + lora_link.py, node_specs.py, constants.py
  math_utils\              geo.py (WGS84↔ENU), quaternion.py  → geometry-conventions
  server\                  server_main.py (orchestrator + main loop),
                           udp_server, websocket_server (JSON WS), foxglove_broadcaster,
                           lora_gateway, ray_builder, voxel_grid (octree),
                           cluster_manager, calibration, uncertainty, visualizer,
                           tracking\ (kalman, association, track_manager, tracker),
                           security\ (key_manager, authenticator),
                           monitoring\ (logger, metrics, node_health), validation\
  rpi\                     Raspberry Pi node (+ gps/imu/vision, LoRa variant)
  esp32\                   esp32_stub.py (software node) + firmware\ (PlatformIO C++)
  android_node\            Kotlin CameraX/ML-Kit node (Gradle project)
  simulation\              sim_node.py — simulated camera swarm (library, no CLI)
  config\node_specs.json   per-node optics registry (FOV/resolution)
  native\                  optional C++ image-processing extension
NEW-UI-V2\                 operator frontend (React 19 + deck.gl + zustand)
VR-UI\                     AR/MR HUD frontend (WebXR + three.js, no React; Steam
                           Frame reference hardware; designators-on-dome overlay
                           + tabletop CIC mode — architecture in VR-UI\README.md)
vr_companion_android\      "GeoTether" Kotlin phone app: GNSS + true-heading feed
                           that anchors VR-UI's HUD mode (the headset has no GNSS)
.claude\skills\            THIS skill library — keep it updated with the code
```

## Entry points & quick commands (from `code\`)

| Goal | Command |
|---|---|
| run server | `python run_server.py --headless` |
| validate | `PYTHONUTF8=1 python system_test.py` (**UTF-8 is mandatory on Windows**; PowerShell: `$env:PYTHONUTF8='1'` first) |
| stress | `PYTHONUTF8=1 python stress_test.py` (one check is known-failing — see `validate-changes`) |
| simulated swarm | see `run-and-debug-server` (library recipe) |
| single fake node | `python esp32/esp32_stub.py --id esp01` or `python rpi/rpi_node.py --mock` |
| keys | `python provision_node.py generate` |

Dependencies: `pip install -r requirements.txt` (websockets, numpy, pyyaml,
scipy — scipy is load-bearing: the tracker's Hungarian assignment in
`server/tracking/data_association.py` hard-imports it).

## What can / cannot be done locally (Windows, this environment)

| Component | Can | Cannot |
|---|---|---|
| Python backend | run, test, debug everything | — |
| NEW-UI-V2 | esbuild syntax check; full browser preview via esm.sh (`ui-development`) | `tsc` typecheck, vite build, npm test (**no node_modules**) |
| VR-UI | esbuild syntax check; flat-mode browser preview (same esm.sh workflow, `?mock=true`, `window.__vrDebug` probes) | XR-session testing (no HMD here), typecheck |
| ESP32 firmware | host-compile `include/lora_protocol.h` byte cross-check (`wire-protocols`) | PlatformIO build/flash |
| Android node / vr_companion_android | code review | Gradle build |

## Provenance & historical artifacts (do not edit)

The live tree (`code\`, `NEW-UI-V2\`) was extracted from a concatenated source
dump mirroring GitHub `AubergineShallow/opticalRadarStuff` branch
`jules-12610216318162572700-ad35271b`, then heavily fixed/extended in-place
(2026-06-30 → 2026-07-03). Everything else at the root is **historical**:
`lumped_source_code*.txt` and `Version\` (old dumps — never edit, never extract
over the live tree), `Code_Review.md` and `lumped_source_code_v2-AUDIT_RESULTS\`
(past review/audit findings — many already fixed; re-verify before acting),
`Discussion.txt` (architecture critique transcript; the LoRa-frustum idea in it
is recorded in `quality-standards`). The tree is **not a git repository**.

## Routing table — which skill for which task

| Task | Skill |
|---|---|
| Run/configure/debug the server; "no tracks appearing" | `run-and-debug-server` |
| Any change is "done"? test suites, adding tests | `validate-changes` |
| Fusion/tracking/octree/calibration/size-estimation; tuning | `tracking-fusion` |
| Coordinates, angles, quaternions, units | `geometry-conventions` |
| Packet formats, changing any wire format | `wire-protocols` |
| LoRa/Meshtastic transports, gateway, radio setup | `lora-meshtastic` |
| RPi / ESP32 / Android node work | `edge-nodes` |
| HMAC keys, signing, auth failures | `security-provisioning` |
| Frontend features/bugs; UI verification | `ui-development` |
| VR/AR frontend (VR-UI) or GeoTether phone app | `ui-development` + `VR-UI\README.md` |
| Foxglove/Flora streaming | `foxglove-addon` |
| Review standards, caps/bounds rules, deferred items | `quality-standards` |

Cross-cutting facts every session should know: config env overrides follow
`OR_<SECTION>_<PARAM>` (`common/config.py`); the ENU origin must agree between
server config, UI constants, and node GPS (`geometry-conventions`); the server
drops telemetry silently for several *deliberate* reasons (`run-and-debug-server`
silent-drop checklist); and the skills in this directory are maintained as part
of the codebase — update them when conventions change.
