---
name: edge-nodes
description: Develop or debug the edge/sensor nodes — Raspberry Pi node (WiFi + LoRa variants), ESP32-CAM firmware (PlatformIO, pin budget, not locally buildable), the esp32_stub software node, the Android node (Kotlin, known open findings), and the node_specs.json optics registry.
---

# Edge Nodes

Four node implementations feed the server. What can be built/run locally:

| Node | Language | Locally runnable? | Locally buildable? |
|---|---|---|---|
| `rpi/rpi_node.py` (+ `lora_node.py`) | Python | YES (`--mock`) | n/a |
| `esp32/esp32_stub.py` | Python | YES | n/a |
| `esp32/firmware/` | C++ (PlatformIO) | no | **NO toolchain here** — except `include/lora_protocol.h` host-compiles (see `wire-protocols`) |
| `android_node/` | Kotlin | no | **NO Gradle here** — validation is review only |

## Raspberry Pi node (`rpi/rpi_node.py`)

The reference V3/UDP node. CLI (`main()`):
`--id/-i` (default `cam01`), `--server/-s` (127.0.0.1), `--port/-p` (5005),
`--config/-c`, `--mock/-m` (mock sensors), `--spec-file` (optics JSON),
`--key-file` (HMAC signing key).

- Sensors: `rpi/gps.py::GPSReader`, `rpi/imu.py::IMUReader`, `rpi/vision.py`
  (detection → camera-relative bearings). **GPS/IMU take `mock=True`; vision
  auto-mocks when OpenCV is absent** (no mock flag) — mock GPS
  wanders around the SF reference origin (37.7749, -122.4194), which matches the
  server's default ENU origin, so a mock node produces working end-to-end data:
  `python rpi/rpi_node.py --mock` from `code\` is the quickest real-node smoke test.
- Announces every 5 s (a lost announce would otherwise strand the node in the
  server's pending pool).
- **Signing** (`_load_signer`): resolution order is (1) `--key-file` — missing
  file RAISES, an operator who asked for signing must not silently run unsigned;
  (2) env `OPTICAL_RADAR_SECRET_KEY`; (3) `/etc/optical_radar/secret.key` then
  `secrets/shared.key` — silently skipped when absent, so unprovisioned nodes run
  unsigned out of the box. Details in `security-provisioning`.

## RPi LoRa variant (`rpi/lora_node.py` + `rpi/lora_edge_tracker.py`)

Bandwidth is the constraint: raw per-frame detections don't fit LoRa airtime, so
`EdgeTracker` (edge-side, deliberately simple) filters noise: a `LocalTrack`
becomes active after `required_hits` (default 10) and dies after `max_missed_sec`
(class default 2.0; `lora_node.py` constructs with 3.0); only ACTIVE ("mature")
tracks are sent as 7-byte UPDATEs. `LocalTrack`
carries `angular_size` — keep it when touching this file (a missing field once
silently zeroed every size sent over LoRa). CLI: `--id` (uint8, default 5),
`--transport` (default `mock`), `--device`, `--baud`.

## ESP32-CAM firmware (`esp32/firmware/`)

PlatformIO project, `board = esp32cam` (AI-Thinker, PSRAM enabled via
`-DBOARD_HAS_PSRAM`). Three envs pick the radio backend by `-D` flag only:
`[env:esp32cam_meshtastic]`, `[env:esp32cam_lora]`, `[env:esp32cam_wifi]`.

Sources: `main.cpp` (loop), `detector.cpp` (frame-difference motion detection),
`edge_tracker.cpp` (C++ mirror of the RPi EdgeTracker concept), `radio.cpp`
(transport backends), `sensors.cpp` (GNSS + IMU), `include/config.h` (ALL pin
and tunable definitions — change pins there, not in sources),
`include/lora_protocol.h` (Arduino-free, host-compilable — the interop anchor).

**Pin budget (from `esp32/firmware/README.md` — read it before wiring):** the
OV2640 + PSRAM claim most GPIOs; free pins are essentially 12, 13, 14, 15, 2, 4
(4 also drives the flash LED). Too few for UART-GNSS + I2C-IMU + SPI-LoRa
simultaneously, so the default puts **GNSS and IMU on one shared I2C bus**
(SDA=13, SCL=12) and gives the radio link its own UART (TX=14, RX=15 → companion
Meshtastic node's Serial Module). GPIO 2/15 are boot-strap pins — the default
assignment respects that; be careful moving them. UART-only NEO-6M GNSS still
supported via `USE_GNSS_I2C 0`.

**Cannot be compiled in this environment** (no PlatformIO/Arduino toolchain).
Validation options: host-compile `lora_protocol.h` byte cross-check
(`wire-protocols`), careful review, and keeping the Python side of every shared
contract under test.

## esp32_stub (`esp32/esp32_stub.py`)

A software stand-in for firmware hardware: `python esp32/esp32_stub.py --id esp01
--server 127.0.0.1` (from `code\`; also `--port`, `--spec-file`). Sends real V3
announces (every 5 s) + telemetry. Its optics come from `config/node_specs.json`
(an ESP32-CAM can't read its lens FOV in software, so it's file-provisioned).
The legacy 17-byte format survives only in its `parse_packet` (compat with old
captures) — never build on it.

## Android node (`android_node/`)

Standalone tracking node: CameraX + ML Kit object detection (`VisionAnalyzer.kt`),
foreground service (`RadarService.kt`), big-endian V3 packets (`UdpClient.kt`).
Orientation comes from Android's fused `TYPE_ROTATION_VECTOR` sensor (not a
hand-rolled filter). Not buildable here (no Gradle/SDK): changes are review-only —
follow `wire-protocols` for packet bytes and mirror `rpi/vision.py` math.

**Known open findings** (from `Code_Review.md`, re-verified against the Kotlin
2026-07-03):

1. **Portrait aspect transposition — OPEN.** `VisionAnalyzer.analyze` passes
   `rotationDegrees` to ML Kit (boxes come back in upright-frame coordinates) but
   normalizes centroids by the UNrotated `imageProxy.width/height`. At 90°/270°
   rotation, azimuth/elevation/angular_size use swapped dimensions. Fix: swap
   width/height when `rotationDegrees % 180 != 0`.
2. **No UDP retry after failed init — OPEN (partially fixed).** The 5 s
   re-announce loop now exists, but if `UdpClient(serverIp, serverPort)` throws in
   the init coroutine `onStartCommand` launches (e.g. DNS failure), the exception
   is swallowed (`printStackTrace`), `udpClient`
   stays null, the announce loop never starts, and nothing retries — the service
   looks alive but transmits nothing. Fix: retry with backoff + surface a health
   status.
3. The historical "IMU smoothing warm-up" finding is SUPERSEDED by the
   ROTATION_VECTOR rewrite. Old Code_Review findings must be re-verified against
   current code before acting — several are already fixed.

## Optics registry (`config/node_specs.json`)

Angular (bearing) uncertainty derives from FOV/resolution — fixed physical lens
properties the hardware can't read back, so they are provisioned in this file,
keyed by node id, with a `_default` fallback entry. Fields: `sensor` (label),
`fov_horizontal/fov_vertical` (deg), `resolution_width/resolution_height` (px).
Adding a node model = adding an entry; **no code change**. Consumers: each node
populates its AnnouncePacket from its own entry (`common/node_specs.py::
load_node_spec`); the server preloads the whole file as pre-announce fallback
(`load_all_specs`) and updates live from announces. LoRa node ids map to keys as
`lora%02d` (e.g. `lora05`).

## Related skills

`wire-protocols` (packet formats + cross-check), `lora-meshtastic` (transports,
gateway, portnums), `security-provisioning` (keys on nodes),
`run-and-debug-server` (what the server does with node packets).
