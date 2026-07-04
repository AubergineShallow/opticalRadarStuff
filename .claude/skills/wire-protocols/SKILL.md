---
name: wire-protocols
description: Reference and change procedure for every wire format in OpticalRadar — the V3 UDP telemetry/announce/command packets, the compressed LoRa ANNOUNCE/UPDATE payloads and serial framing, the C++ firmware mirror, endianness and quantization invariants, and the byte-level Python↔C++ cross-check to run before shipping any protocol change.
---

# Wire Protocols

Two protocol families exist. **They have different endianness — this is the #1 trap:**

| Family | Defined in | Endianness | Carried over |
|---|---|---|---|
| V3 (telemetry/announce/command) | `common/protocol.py` | **big**-endian (`>`) | UDP :5005 (WiFi) |
| LoRa micro-payloads | `common/lora_protocol.py` + C++ mirror `esp32/firmware/include/lora_protocol.h` | **little**-endian (`<`) | Meshtastic / raw serial / UDP :5006 |

## V3 telemetry packet (`TelemetryPacket`, type 0x01)

Header is exactly `HEADER_SIZE = 61` bytes, then `N × 8`-byte MotionVectors, then an
optional trailing 32-byte HMAC (`SIGNATURE_SIZE`). All big-endian.

| Offset | Size | Type | Field |
|---|---|---|---|
| 0 | 1 | B | version (=3, `common/constants.py::VERSION`) |
| 1 | 1 | B | packet_type (0x01) |
| 2 | 8 | bytes | camera_id (UTF-8, null-padded, **max 8 bytes** — longer ids are truncated) |
| 10 | 4 | I | sequence_number |
| 14 | 8 | d | timestamp (unix float64) |
| 22 | 8 | d | latitude (deg) |
| 30 | 8 | d | longitude (deg) |
| 38 | 4 | f | altitude (m) |
| 42 | 16 | ffff | orientation quaternion **[w, x, y, z]** |
| 58 | 1 | B | health_flags (bit0 GPS, bit1 camera, bit2 IMU — `constants.py::HEALTH_FLAG_*`) |
| 59 | 2 | H | vector_count (uint16 — V3 raised this from uint8) |

**Signature auto-detection**: there is no has-signature flag on the wire. Any bytes
remaining after header + `vector_count × 8` that are ≥ 32 are taken as the HMAC
(`TelemetryPacket.unpack`). Consequence: never append other trailing data.

### MotionVector (8 bytes, `>HhBBH`)

| Field | Wire type | Encoding | Decode |
|---|---|---|---|
| azimuth | H | `int(az/360*65535)` — [0,360) scaled | `raw/65535*360` |
| elevation | h | `int(el/90*32767)`, clamped ±32768/32767 — [-90,90] scaled | `raw/32767*90` |
| intensity | B | 0–255 | as-is |
| class_id | B | 0–255 | as-is |
| angular_size | H | `int(size/180*65535)`, clamped — [0,180] deg | `raw/65535*180` |

Azimuth/elevation are **camera-relative bearings**; the server world-rotates them
using the header quaternion (`server/ray_builder.py`).

## V3 announce packet (`AnnouncePacket`, type 0x04, 31 bytes + optional 32 HMAC)

`>BB` version+type, 8-byte camera_id, `>d` timestamp, then payload `>ffHHB`:
fov_horizontal, fov_vertical, resolution_width, resolution_height, fps.
Announces ARE signable (`get_data_for_signing`) — an unsigned announce used to
bypass verification entirely and could poison node registration; the server now
verifies every inbound packet type when security is on (`server_main._process_packet`).

## V3 command packet (`CommandPacket`, type 0x02, server → node)

`>BB` + camera_id(8) + `>B` command_type + `>H` payload_len + payload + optional
HMAC. Types: `CMD_CALIBRATION_UPDATE=0x01`, `CMD_CONFIG_UPDATE=0x02`, `CMD_RESTART=0x03`.

## Ground truth (type 0x03)

Same wire format as telemetry, `packet_type=0x03`. There is **no target_id field**:
the sender encodes one target per pseudo-camera_id (e.g. `GT-1`) and the server uses
camera_id as target identity (`server_main._process_ground_truth_packet`).

## Legacy 17-byte ESP32 format

Survives ONLY in `esp32/esp32_stub.py::parse_packet` for compatibility with old
capture files. The stub's SEND path emits real V3 telemetry. Never build anything
new on the 17-byte format.

## LoRa micro-payloads (little-endian!)

Airtime is the scarce resource; angles are quantized hard.

**ANNOUNCE — 20 bytes, `<BBfffhhh`** (sent ~every 5 s; the node's pose):
type=0x01, node_id (uint8), lat/lon/alt (float32), roll/pitch/yaw as **int16
centidegrees** (`wrap180(angle) * 100`, truncated).

**UPDATE — 7 bytes, `<BBBHbB`** (sent per mature track; one bearing):
type=0x02, node_id, track_id (uint8), azimuth uint16 (`(az%360)/360*65535`),
elevation **int8 whole degrees** (clamped ±128/127), angular_size uint8
(`size/180*255`).

Decoding: `common/lora_protocol.py::unpack_lora` — strict length match required
(20 or 7 bytes exactly), else None.

**Node identity**: uint8 node_id ↔ string camera_id via
`node_id_to_camera_id(5) == "lora05"` (prefix configurable, `lora.node_id_prefix`).

### Serial framing (raw byte-stream links only)

Meshtastic delivers discrete messages — no framing. Raw serial (SX127x bridge)
needs `frame_payload`: `AA 55 | len(1) | payload | crc16_ccitt(payload) LE(2)`.
`LoRaFramer.push()` deframes incrementally: resyncs past garbage and bad CRCs, and
rejects any length byte > `max_payload` (default 64) as a false sync — without
that bound a spurious `AA 55` + large length stalled the framer forever (real bug,
covered by stress S1's `test_framer_split_and_corrupt`).

## Interop invariants (Python ↔ C++ must agree byte-for-byte)

1. **Quantization TRUNCATES toward zero.** Python `int()` truncates; the C++
   mirror uses `trunc_toward_zero` ((long) cast). NEVER use `lroundf`/`round` on
   either side — a value like 3.7° would round to 4 on one side and truncate to 3
   on the other, and the cross-check below will catch it.
2. **wrap180 before centidegree encoding.** int16 centidegrees spans only
   ±327.67°, so a 330° yaw must become −30° first (`wrap180`, both sides). Lossless
   for the server: it consumes orientation via periodic `from_euler`.
3. **Endianness per family** (V3 big, LoRa little). The C++ header writes
   integers explicitly low-byte first (`le_put_u16`), but `le_put_f32` is a
   plain memcpy that assumes a little-endian host — fine for ESP32 (Xtensa)
   and x86, NOT portable to a big-endian host.
4. **CRC-16/CCITT-FALSE** (init 0xFFFF, poly 0x1021) — `crc16_ccitt` in Python,
   `lora_crc16_ccitt` in C++.

## Changing a protocol safely — checklist

1. Change `common/protocol.py` or `common/lora_protocol.py` AND every consumer:
   the C++ mirror `esp32/firmware/include/lora_protocol.h`, firmware call sites
   (`esp32/firmware/src/`), node senders (`rpi/`, `simulation/sim_node.py`,
   `esp32/esp32_stub.py`, Android `UdpClient.kt`/`VisionAnalyzer.kt` for V3), and
   the server parsers/gateway.
2. Update/extend system_test Phase 2 (V3 round-trip) or Phase 16 (LoRa) and run
   the suites (`validate-changes` skill).
3. **Run the byte cross-check** (verified working 2026-07-04, g++ available in
   Git Bash). Compile a tiny harness against the real header:

```bash
SCRATCH=$(mktemp -d) && cat > "$SCRATCH/xcheck.cpp" <<'EOF'
#include <cstdio>
#include <cstdint>
#include <cstring>
#include "lora_protocol.h"
int main() {
    uint8_t buf[32];
    int n = lora_pack_announce(buf, 5, 37.7749f, -122.4194f, 12.5f, 1.25f, -3.5f, 330.0f);
    for (int i = 0; i < n; i++) printf("%02x", buf[i]); printf("\n");
    n = lora_pack_update(buf, 5, 9, 123.456f, -12.0f, 4.5f);
    for (int i = 0; i < n; i++) printf("%02x", buf[i]); printf("\n");
    return 0;
}
EOF
g++ -std=c++11 -I "<project>/code/esp32/firmware/include" -o "$SCRATCH/xcheck" "$SCRATCH/xcheck.cpp" && "$SCRATCH/xcheck"
```

then the Python side (from `code\`):

```bash
python -c "
from common.lora_protocol import LoraAnnouncePacket, LoraUpdatePacket
print(LoraAnnouncePacket(5, 37.7749, -122.4194, 12.5, 1.25, -3.5, 330.0).pack().hex())
print(LoraUpdatePacket(5, 9, 123.456, -12.0, 4.5).pack().hex())
"
```

Both must print identical lines. Reference output with today's header/module:

```
01057f191742bcd6f4c2000048417d00a2fe48f4
020509ca57f406
```

(Note the 330° yaw case in the test values — it exercises wrap180, and −12.0
elevation exercises signed truncation. Keep such edge values in the harness.)

4. Version discipline: V3 wire layout is frozen. Additive needs (e.g. a battery
   field — see the deliberate omission in `server_main` node_update) require a
   protocol **V4** with a version bump, not a silent field append (the trailing
   bytes are already claimed by signature auto-detection).

## Related skills

`lora-meshtastic` (transports/gateway around these payloads), `edge-nodes`
(firmware/node senders), `geometry-conventions` (angle/quaternion conventions),
`security-provisioning` (what the HMAC covers), `validate-changes` (test phases).