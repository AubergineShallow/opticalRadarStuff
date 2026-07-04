---
name: lora-meshtastic
description: Work on the LoRa/Meshtastic ingest path — transport abstraction (Meshtastic/serial/UDP/loopback), the stateful LoRaGateway that feeds the server pipeline, config and env setup, hardware requirements (radio on the laptop), portnum rules, and how to test it all without any radio hardware.
---

# LoRa / Meshtastic Ingest Path

Edge detections can arrive over LoRa in parallel with WiFi/UDP. The wire format
lives in `wire-protocols`; this skill covers everything around it. Human-facing
setup guide: `code/LORA_SETUP.md` (accurate; keep it in sync when changing this
subsystem).

## Architecture

```
node → [transport: Meshtastic mesh | raw serial | UDP:5006 | loopback]
     → common/lora_link.py (bytes)
     → server/lora_gateway.py LoRaGateway (translate + synthesize)
     → same ReceivedPacket objects as UDPServer
     → server_main._process_packet(trusted=True)   ← same pipeline as UDP
```

Two design decisions to preserve:

1. **The gateway mirrors `UDPServer`'s surface** (`start/stop/get_packets/
   get_stats/is_running`) and emits an identical `ReceivedPacket` dataclass, so
   `server_main._run_loop` drains both sources with zero special-casing.
2. **The gateway is STATEFUL by necessity.** A 7-byte UPDATE has no room for
   pose; pose arrives in the periodic 20-byte ANNOUNCE. `LoRaGateway` caches the
   latest pose per node (`_poses`) and synthesizes a full V3 `TelemetryPacket`
   (pose + one MotionVector) per UPDATE; ANNOUNCEs become V3 `AnnouncePacket`s
   with optics looked up from `config/node_specs.json` (`load_node_spec`, falls
   back to the file's `_default` entry — the LoRa announce spends no bytes on
   FOV/resolution). An UPDATE arriving before any ANNOUNCE is dropped and counted
   (`orphan_updates` in `get_stats()`); this self-heals on the next announce.

Other gateway facts (all in `server/lora_gateway.py`): synthesized telemetry gets
`health_flags=0x07` (nominal) and `intensity=200` (`LORA_DETECTION_INTENSITY` —
the UPDATE carries no per-detection intensity); per-node sequence numbers are
gateway-generated; the queue is bounded at 1000 (drops newest, counted).

**Trust model**: LoRa packets carry NO HMAC (no airtime for it; the link is
physically scoped). `server_main._run_loop` passes them to `_process_packet` with
`trusted=True`, bypassing the signature gate. Know this before deploying where
RF injection is a realistic threat — see `security-provisioning`.

## Transports (`common/lora_link.py`)

Selected by `make_transport(kind, ...)` from config `lora.transport`:

| kind | Class | Needs | Notes |
|---|---|---|---|
| `meshtastic` (default) | `MeshtasticTransport` | Meshtastic radio on USB + `pip install meshtastic` | `device=""` auto-detects; `tcp_host` attaches over TCP instead |
| `serial` | `SerialLoRaTransport` | SX127x serial bridge + pyserial | **requires** `lora.device` (COM7 / /dev/ttyUSB0) — `make_transport` raises at config time if empty (pyserial's port=None trap) |
| `udp` | `UDPLoRaTransport` | nothing (LAN) | binds `lora.udp_port` (5006) — deliberately ≠ 5005 (V3 UDP) |
| `loopback` | `LoopbackTransport` | nothing | in-process, for tests |

Serial transports use `LoRaFramer` (sync `AA 55`, CRC-16/CCITT-FALSE, plausible-
length guard `max_payload=64` — see `wire-protocols`). Meshtastic and UDP deliver
discrete messages: **no framing**.

**Portnum rules (Meshtastic)**: both ends must agree. The gateway accepts TWO
ports (`MeshtasticTransport._accept_ports`): `PRIVATE_APP = 256`
(`MESHTASTIC_PORTNUM`, used by nodes driving the Python API directly — the RPi
path, and what the gateway itself sends on) and `SERIAL_APP = 64`
(`MESHTASTIC_SERIAL_APP_PORTNUM`, where payloads from an ESP32-CAM feeding a
companion radio's Serial Module arrive). Some meshtastic lib versions report
portnum as int, others as string — the transport handles both; keep that if you
touch it.

## Configuration

`LoRaConfig` in `common/config.py`; env pattern `OR_LORA_<PARAM>`:

| Key | Default | Notes |
|---|---|---|
| `lora.enabled` | False | gateway is built only if true (`server_main._build_lora_gateway`) |
| `lora.transport` | `meshtastic` | see table above |
| `lora.device` | `""` | serial device / meshtastic devPath; `""` = auto-detect |
| `lora.baud` | 115200 | serial transport only |
| `lora.udp_port` | 5006 | udp transport only |
| `lora.tcp_host` | `""` | set to use a TCP-attached meshtastic node |
| `lora.portnum` | 256 | PRIVATE_APP; both ends agree |
| `lora.channel_index` | 0 | meshtastic channel |
| `lora.node_id_prefix` | `lora` | uint8 id → camera_id (5 → `lora05`) |

Quick start: `OR_LORA_ENABLED=true OR_LORA_TRANSPORT=meshtastic python run_server.py`
(from `code\`; PowerShell: `$env:OR_LORA_ENABLED='true'; ...`). Deps:
`pip install -r requirements-lora.txt` (meshtastic + pyserial).

Failure behavior (deliberate, keep it): `_build_lora_gateway` catches construction
errors → logs + returns None; `start()` failures (missing radio) are caught in
`OpticalRadarServer.start()` → logged, `lora_server=None`, **UDP path unaffected**.
Transport construction never touches hardware; only `.start()` does.

## Hardware reality

- **The laptop/server MUST have a radio physically attached** for meshtastic/
  serial transports — LoRa is a radio PHY; nothing arrives "out of the air".
  Default path: a Meshtastic device (Heltec/RAK/LilyGO) on USB.
- ESP32-CAM nodes hand payloads to a **companion Meshtastic radio over UART**
  (radio's Serial Module in SIMPLE/PROTO mode @115200) → arrives on SERIAL_APP=64.
- RPi nodes use the meshtastic Python API directly → PRIVATE_APP=256.
- All radios: same channel + region, stock Meshtastic firmware. Full walk-through
  in `code/LORA_SETUP.md`.

## Testing without hardware

- `LoopbackTransport`: instantiate gateway + transport in-process, `send()` packed
  payloads, drain `get_packets()`. This is how system_test Phase 16 (11 checks)
  works — read `test_lora_suite` in `code/system_test.py` for ready-made patterns
  (announce→update statefulness, framer resync, end-to-end into
  `server._process_packet`). Stress S11 skips the transport and drives
  `gw._ingest(payload, ts)` directly against a stub.
- `UDPLoRaTransport` on localhost exercises a real socket path (also in Phase 16).
- End-to-end with a live server: enable `udp` transport and send packed
  `LoraAnnouncePacket` + `LoraUpdatePacket` bytes to 127.0.0.1:5006.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Gateway logs `LoRa gateway failed to start`, server continues | no radio / wrong device | attach radio, set `lora.device`, or disable `lora.enabled` |
| `serial LoRa transport requires a device` in the log | `transport=serial` with empty `lora.device` | set `OR_LORA_DEVICE=COM7` (deliberate fail-fast in `make_transport`; a node CLI exits, the server catches it and continues UDP-only) |
| Updates arrive, no tracks; `orphan_updates` climbing | node never announced (or gateway restarted, losing pose cache) | wait for the ≤5 s re-announce; check node announce loop |
| Meshtastic messages visibly arriving but gateway ignores them | portnum mismatch | node must send on 256 (API) or via Serial Module (64); check `lora.portnum` |
| Serial stream decodes nothing | framing mismatch or wrong baud | sender must use `frame_payload`; baud both ends 115200 |
| Node appears as wrong id | `node_id_prefix` mismatch vs `config/node_specs.json` keys | ids are `lora%02d` — spec keys must match |

## Related skills

`wire-protocols` (payload bytes, framer, C++ cross-check), `edge-nodes` (RPi
`lora_node.py`, ESP32 firmware envs), `run-and-debug-server` (pipeline after the
gateway), `validate-changes` (Phase 16 / S11).
