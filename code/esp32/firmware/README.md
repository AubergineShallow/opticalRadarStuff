# ESP32-CAM Optical Tracking Node (firmware)

An ESP32-CAM (AI-Thinker, OV2640) that does on-board motion detection, reads its
own **GNSS** fix and **IMU** orientation, and reports compressed bearings to the
server over **Meshtastic** (default), raw **LoRa (SX127x)**, or **WiFi/UDP**.

The wire format is byte-for-byte identical to `code/common/lora_protocol.py`
(`include/lora_protocol.h` is the mirror; the two are cross-checked in CI-style
by the host test described below), so the server's `LoRaGateway` ingests these
payloads through the exact same pipeline as the UDP camera nodes.

## Pipeline

```
OV2640 grayscale frame ──► frame-diff detector ──► maturation edge-tracker
        │                                                   │
   GNSS (NEO-6M/M8N/M9N)                         mature tracks → LoRa UPDATE (7B)
   IMU  (MPU-6050/BNO08x)  ── pose ──► LoRa ANNOUNCE (20B, every 5s)
                                                   │
                                       radio backend (Meshtastic / SX127x / WiFi)
```

## Radio backends (choose the PlatformIO env)

| Env | Backend | Server side |
| --- | --- | --- |
| `esp32cam_meshtastic` *(default)* | Payload → companion Meshtastic node over UART (Serial Module) → mesh | `lora.transport = "meshtastic"` |
| `esp32cam_lora` | Direct SX1278 via RadioLib (raw point-to-point) | `lora.transport = "serial"` (USB LoRa bridge) |
| `esp32cam_wifi` | Compressed payloads over WiFi/UDP | `lora.transport = "udp"` |

```bash
pio run -e esp32cam_meshtastic -t upload
pio device monitor -b 115200
```

## The tight ESP32-CAM pin budget (read this before wiring)

The OV2640 + PSRAM claim most GPIOs. With the microSD slot **unused**, the free
pins are essentially **GPIO 12, 13, 14, 15, 2, 4** (GPIO 4 also drives the flash
LED) plus UART0 (1/3, used for USB logging). That is not enough for a camera +
UART-GNSS + I2C-IMU + SPI-LoRa all at once.

The firmware default resolves this by putting **GNSS and IMU on one shared I2C
bus** (NEO-M8N/M9N and MPU-6050/BNO08x all speak I2C) and giving the radio link
its own UART. A UART-only NEO-6M is still supported (`USE_GNSS_I2C 0`).

### Default wiring (Meshtastic backend, I2C GNSS + IMU)

| Signal | ESP32-CAM pin | To |
| --- | --- | --- |
| I2C SDA | GPIO 13 | GNSS SDA **and** IMU SDA |
| I2C SCL | GPIO 12 | GNSS SCL **and** IMU SCL |
| UART TX | GPIO 14 | Meshtastic node Serial **RX** |
| UART RX | GPIO 15 | Meshtastic node Serial **TX** |
| 5V / GND | 5V / GND | all peripherals (regulate as needed) |

> GPIO 2 and 15 are boot-strapping pins on the ESP32; the assignment above keeps
> them free of pull states that block boot, but if the board refuses to boot with
> peripherals attached, disconnect them during power-up. All of this is declared
> in `include/config.h` — change pins there, not in the source.

### Direct SX127x backend (`esp32cam_lora`)

Reuses the SD-card pins for SPI, so the SD card must stay unused:
`SCK=14, MISO=12, MOSI=13, CS=15, DIO0=2, RST=4` (see `config.h`). This leaves no
easy pins for I2C sensors simultaneously — use this backend when the node's pose
is fixed/provisioned rather than live, or move sensors to a companion MCU.

## Configuration (`include/config.h`)

- `NODE_ID` — uint8 id. The server maps it to `lora<NN>` (e.g. 20 → `lora20`).
  **Add a matching entry** in `code/config/node_specs.json` with this node's FOV
  and resolution (the sensor cannot report its lens FOV electronically).
- `FOV_HORIZONTAL_DEG` / `FOV_VERTICAL_DEG` — keep in sync with `node_specs.json`.
- Detection thresholds, track maturation, announce/update cadence, LoRa region
  frequency (`915` US / `868` EU / `433`), pins.

## Notes on the orientation encoding

The ANNOUNCE packs roll/pitch/yaw as int16 centidegrees, wrapped to [-180,180)
(`wrap180`), so a heading of 330° is sent as -30° — lossless for the server,
which consumes orientation through a periodic `from_euler()`. The MPU-6050 has no
magnetometer, so its **yaw is gyro-integrated and drifts**; provision a fixed
installation heading or use a BNO08x for absolute yaw.

## Verifying the wire format matches the server

`include/lora_protocol.h` has **no Arduino dependencies**, so it compiles on a
host to cross-check the bytes against Python:

```bash
g++ -I include -x c++ - <<'EOF' -o /tmp/pc && /tmp/pc
#include "lora_protocol.h"
#include <cstdio>
int main(){uint8_t a[LORA_ANNOUNCE_SIZE];
  lora_pack_announce(a,20,37.7749f,-122.4194f,12,1.5f,-3.25f,91);
  for(int i=0;i<LORA_ANNOUNCE_SIZE;i++)printf("%02x",a[i]);printf("\n");}
EOF
```

Compare with `python -c "from common.lora_protocol import LoraAnnouncePacket as A;
print(A(20,37.7749,-122.4194,12,1.5,-3.25,91).pack().hex())"`.
