"""
lora_protocol.py
PURPOSE: Defines a highly compressed micro-payload for LoRa / Meshtastic / LoRaWAN
         links, plus the byte-stream framing and node-id mapping that the
         server-side gateway (server.lora_gateway) and the edge nodes share.

Two payload types travel over the air:

  * ANNOUNCE (20 bytes) - sent every few seconds. Carries the node's live GNSS
    fix and IMU orientation so the server can place its rays. This is the LoRa
    analogue of common.protocol.AnnouncePacket + the pose fields of a
    TelemetryPacket header.
  * UPDATE (7 bytes) - sent per mature track. Carries one camera-relative
    bearing (azimuth/elevation) plus an apparent angular size.

The angles are quantised hard because LoRa airtime is the scarce resource: a
7-byte update fits in a single short spreading-factor frame with room to spare.

TRANSPORTS AND FRAMING
----------------------
Meshtastic and LoRaWAN both deliver each application payload as a *discrete*
message, so the 20/7-byte payload above is transmitted verbatim and no framing
is required on those links. A raw point-to-point serial link (an SX127x bridge
on the laptop's USB, or the RPi's LoRa HAT read as a byte stream) has no message
boundaries, so LoRaFramer wraps each payload as:

    0xAA 0x55 | len(1) | payload(len) | crc16_ccitt(payload) little-endian(2)

LoRaFramer.push() is resilient to partial reads and resynchronises on a bad CRC.
"""

import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------
MSG_TYPE_ANNOUNCE = 0x01
MSG_TYPE_UPDATE = 0x02

ANNOUNCE_SIZE = 20  # <BBfffhhh : 1+1+4+4+4+2+2+2
UPDATE_SIZE = 7     # <BBBHbB   : 1+1+1+2+1+1

# Default string prefix used to turn a uint8 LoRa node id into the string
# camera_id the server pipeline keys everything on (e.g. 5 -> "lora05").
DEFAULT_NODE_ID_PREFIX = "lora"


def wrap180(angle_deg: float) -> float:
    """Wrap an angle into [-180, 180).

    The announce encodes each orientation angle as int16 centidegrees, which
    only spans +/-327.67 deg. A yaw/heading of 0..360 would overflow above
    327.67, so headings are wrapped first: 330 -> -30. This is lossless for the
    server, which consumes orientation through from_euler() (periodic in 360).
    """
    return ((angle_deg + 180.0) % 360.0) - 180.0


def node_id_to_camera_id(node_id: int, prefix: str = DEFAULT_NODE_ID_PREFIX) -> str:
    """Map a uint8 LoRa node id to the server's string camera_id."""
    return f"{prefix}{int(node_id) & 0xFF:02d}"


def camera_id_to_node_id(camera_id: str, prefix: str = DEFAULT_NODE_ID_PREFIX) -> Optional[int]:
    """Inverse of node_id_to_camera_id. Returns None if it does not match."""
    if prefix and camera_id.startswith(prefix):
        tail = camera_id[len(prefix):]
        if tail.isdigit():
            return int(tail) & 0xFF
    return None


@dataclass
class LoraAnnouncePacket:
    """
    Sent periodically (e.g. every 5 s) so the server always has a fresh pose.
    Size: 20 bytes.
    [uint8 type][uint8 node_id][float32 lat][float32 lon][float32 alt]
    [int16 roll*100][int16 pitch*100][int16 yaw*100]
    """
    node_id: int
    lat: float
    lon: float
    alt: float
    roll_deg: float
    pitch_deg: float
    yaw_deg: float

    def pack(self) -> bytes:
        # GPS as float32; angles wrapped to [-180,180) then compressed to
        # centidegrees in an int16 (the clamp is now just a safety net).
        roll_comp = max(-32768, min(32767, int(wrap180(self.roll_deg) * 100)))
        pitch_comp = max(-32768, min(32767, int(wrap180(self.pitch_deg) * 100)))
        yaw_comp = max(-32768, min(32767, int(wrap180(self.yaw_deg) * 100)))
        return struct.pack('<BBfffhhh',
                           MSG_TYPE_ANNOUNCE,
                           self.node_id & 0xFF,
                           self.lat, self.lon, self.alt,
                           roll_comp, pitch_comp, yaw_comp)


@dataclass
class LoraUpdatePacket:
    """
    Sent per mature track. Size: 7 bytes.
    [uint8 type][uint8 node_id][uint8 track_id][uint16 az][int8 el][uint8 size]

    azimuth/elevation are CAMERA-RELATIVE bearings (matching the UDP
    MotionVector convention); the server rotates them into the world frame
    using the pose from the most recent ANNOUNCE.
    """
    node_id: int
    track_id: int
    azimuth: float   # [0, 360)
    elevation: float  # [-90, 90]
    angular_size: float = 0.0  # [0, 180]

    def pack(self) -> bytes:
        # Azimuth: 0-360 -> uint16
        az_comp = int((self.azimuth % 360.0) / 360.0 * 65535) & 0xFFFF
        # Elevation: clamp to int8 degrees
        el_comp = max(-128, min(127, int(self.elevation)))
        # Angular size: 0-180 -> uint8
        size_comp = max(0, min(255, int((self.angular_size / 180.0) * 255)))
        return struct.pack('<BBBHbB',
                           MSG_TYPE_UPDATE,
                           self.node_id & 0xFF,
                           self.track_id & 0xFF,
                           az_comp,
                           el_comp,
                           size_comp)


def unpack_lora(data: bytes):
    """Decode one raw LoRa payload into its packet dataclass, or None."""
    if not data:
        return None
    msg_type = data[0]
    if msg_type == MSG_TYPE_ANNOUNCE and len(data) == ANNOUNCE_SIZE:
        u = struct.unpack('<BBfffhhh', data)
        return LoraAnnouncePacket(
            node_id=u[1],
            lat=u[2], lon=u[3], alt=u[4],
            roll_deg=u[5] / 100.0,
            pitch_deg=u[6] / 100.0,
            yaw_deg=u[7] / 100.0,
        )
    if msg_type == MSG_TYPE_UPDATE and len(data) == UPDATE_SIZE:
        u = struct.unpack('<BBBHbB', data)
        return LoraUpdatePacket(
            node_id=u[1],
            track_id=u[2],
            azimuth=(u[3] / 65535.0) * 360.0,
            elevation=float(u[4]),
            angular_size=(u[5] / 255.0) * 180.0,
        )
    return None


# ---------------------------------------------------------------------------
# Byte-stream framing (only needed for raw serial transports)
# ---------------------------------------------------------------------------
FRAME_SYNC = b'\xAA\x55'


def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE. Small and mirrorable in the ESP32 C++ firmware."""
    for byte in data:
        crc ^= (byte << 8) & 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def frame_payload(payload: bytes) -> bytes:
    """Wrap a payload for transmission over an unframed byte stream."""
    if len(payload) > 255:
        raise ValueError("LoRa payload too large to frame (>255 bytes)")
    crc = crc16_ccitt(payload)
    return FRAME_SYNC + bytes([len(payload)]) + payload + struct.pack('<H', crc)


class LoRaFramer:
    """
    Incremental deframer for a raw serial byte stream. Feed it whatever
    bytes arrive; it returns the complete, CRC-checked payloads found so far
    and buffers the rest. Resynchronises past corruption automatically.
    """

    def __init__(self, max_buffer: int = 4096, max_payload: int = 64):
        self._buf = bytearray()
        self._max_buffer = max_buffer
        # Longest payload the deframer will wait for. The LoRa micro-payloads are
        # tiny (ANNOUNCE 20 B, UPDATE 7 B), so any length byte far above that is a
        # false sync, not a real length. Without this bound a spurious 0xAA55
        # followed by a large length byte makes the framer wait for a frame bigger
        # than the whole remaining stream — stalling and swallowing every real
        # frame behind it. Rejecting the implausible length lets it resync.
        self._max_payload = max_payload

    def push(self, data: bytes) -> List[bytes]:
        """Append received bytes and return any completed payloads."""
        self._buf.extend(data)
        # Bound memory if we never find a valid frame (pure noise).
        if len(self._buf) > self._max_buffer:
            del self._buf[:-self._max_buffer]

        out: List[bytes] = []
        while True:
            # Find the sync word.
            idx = self._buf.find(FRAME_SYNC)
            if idx < 0:
                # Keep only a trailing byte that might be a partial sync.
                if self._buf and self._buf[-1] == FRAME_SYNC[0]:
                    del self._buf[:-1]
                else:
                    self._buf.clear()
                break
            if idx > 0:
                del self._buf[:idx]  # drop leading garbage

            # Need sync(2) + len(1) to know the frame length.
            if len(self._buf) < 3:
                break
            length = self._buf[2]

            # An implausibly large length means this sync word is spurious (noise
            # or the tail of a corrupted frame). Skip past it and resync on the
            # next candidate instead of blocking on a frame that will never come.
            if length > self._max_payload:
                del self._buf[:2]
                continue

            total = 2 + 1 + length + 2  # sync + len + payload + crc
            if len(self._buf) < total:
                break  # wait for the rest

            payload = bytes(self._buf[3:3 + length])
            crc_rx = struct.unpack('<H', bytes(self._buf[3 + length:3 + length + 2]))[0]
            if crc16_ccitt(payload) == crc_rx:
                out.append(payload)
                del self._buf[:total]
            else:
                # Bad CRC: drop the sync byte and resync from the next one.
                del self._buf[:2]
        return out
