
# LoRa / Meshtastic Setup

This system can ingest edge-node detections over **LoRa** in addition to the
existing WiFi/UDP path. The compressed on-air format
(`common/lora_protocol.py`) is transport-agnostic; three transports carry it:

| Transport | Node hardware | What the **laptop/server** needs | `lora.transport` |
| --- | --- | --- | --- |
| **Meshtastic** *(default)* | ESP32-CAM/RPi + companion Meshtastic radio | **A Meshtastic node on USB** + `pip install meshtastic` | `meshtastic` |
| Raw LoRa (SX127x) | ESP32-CAM/RPi + SX127x | A LoRa radio on USB running a serial bridge + `pip install pyserial` | `serial` |
| WiFi/UDP | ESP32-CAM on WiFi | Nothing extra (same LAN) | `udp` |

> **Yes — the laptop needs a radio physically attached.** A laptop cannot
> receive LoRa "out of the air"; LoRa/Meshtastic/LoRaWAN are all radio PHYs. For
> the default Meshtastic path you plug a Meshtastic device (Heltec/RAK/LilyGO)
> into the laptop over USB, and the server talks to it with the `meshtastic`
> Python library. The mesh handles multi-hop relaying between remote nodes for
> free.

```
[ESP32-CAM node] --UART--> [Meshtastic radio] ~~~mesh (multi-hop)~~~ [Meshtastic radio on laptop USB] --> LoRaGateway --> tracking pipeline
```

## 1. Server (laptop)

Install the optional deps and enable the gateway. It stays **off by default** —
enabling it only makes sense once a radio is attached.

```bash
pip install -r requirements-lora.txt      # meshtastic + pyserial
```

Enable via `config.yaml`:

```yaml
lora:
  enabled: true
  transport: meshtastic     # meshtastic | serial | udp
  device: ""                # "" = auto-detect the USB Meshtastic node; else COM7 / /dev/ttyUSB0
  node_id_prefix: lora       # uint8 node id -> camera_id  (20 -> "lora20")
  # serial transport only:  baud: 115200
  # udp transport only:     udp_port: 5006
```

…or via environment variables (no config file needed):

```bash
OR_LORA_ENABLED=true OR_LORA_TRANSPORT=meshtastic python run_server.py
```

On startup you'll see `LoRa gateway configured (transport=meshtastic)` and, once
a node announces, the same node/track updates the UDP nodes produce. A
missing/misconfigured radio is logged and skipped — the UDP path keeps working.

## 2. The Meshtastic radios

Flash stock [Meshtastic](https://meshtastic.org) firmware on both the laptop's
node and each node's companion radio, put them on the **same channel/region**,
and on the companion radios enable the **Serial Module** (SIMPLE/PROTO mode) at
`115200` so bytes from the ESP32-CAM's UART are injected into the mesh. The
server accepts payloads on both `PRIVATE_APP` (Python-API senders like the RPi)
and `SERIAL_APP` (Serial-Module senders like the ESP32-CAM).

## 3. Edge nodes

- **ESP32-CAM**: see [`esp32/firmware/README.md`](esp32/firmware/README.md).
  Build `pio run -e esp32cam_meshtastic -t upload`. Set `NODE_ID` in
  `include/config.h` and add a matching entry to `config/node_specs.json`.
- **Raspberry Pi**: `python -m rpi.lora_node --id 5 --transport meshtastic
  --device /dev/ttyUSB0` (or `--transport serial` for a LoRa HAT, or `mock` to
  print framed bytes with no hardware).

## 4. Node ids and optics

Each node has a `uint8` id the server maps to a string `camera_id`
(`20 → lora20`). Add that id to [`config/node_specs.json`](config/node_specs.json)
with the node's FOV/resolution so its bearing uncertainty reflects the real
optics — the sensor cannot report its lens FOV electronically.

## Why not LoRaWAN?

LoRaWAN needs a gateway plus a network server (ChirpStack/TTN) and is aimed at
star topologies with internet backhaul — heavy for an austere field setup.
Meshtastic gives multi-hop mesh relaying with nothing but the radios themselves,
which is why it's the default here. The gateway is transport-pluggable, so a
LoRaWAN bridge could be added as another transport later if needed.
