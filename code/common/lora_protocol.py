"""
lora_protocol.py
PURPOSE: Defines a highly compressed micro-payload for LoRaWAN communication.
"""

import struct
from dataclasses import dataclass
from typing import Tuple

# Message Types
MSG_TYPE_ANNOUNCE = 0x01
MSG_TYPE_UPDATE = 0x02

@dataclass
class LoraAnnouncePacket:
    """
    Sent only once upon boot.
    Registers the node's static GPS and orientation with the server.
    Size: 22 bytes
    [uint8 type][uint8 node_id][float32 lat][float32 lon][float32 alt][int16 roll][int16 pitch][int16 yaw]
    """
    node_id: int
    lat: float
    lon: float
    alt: float
    roll_deg: float
    pitch_deg: float
    yaw_deg: float

    def pack(self) -> bytes:
        # Pack floats for GPS, compress angles to int16 (-180 to 180 degrees * 100)
        roll_comp = int(self.roll_deg * 100)
        pitch_comp = int(self.pitch_deg * 100)
        yaw_comp = int(self.yaw_deg * 100)
        return struct.pack('<BBfffhhh',
                           MSG_TYPE_ANNOUNCE,
                           self.node_id,
                           self.lat, self.lon, self.alt,
                           roll_comp, pitch_comp, yaw_comp)

@dataclass
class LoraUpdatePacket:
    """
    Sent periodically (e.g. every 5 seconds) to update track positions.
    Size: 6 bytes
    [uint8 type][uint8 node_id][uint8 track_id][uint16 az][int8 el]
    """
    node_id: int
    track_id: int
    azimuth: float   # [0, 360)
    elevation: float # [-90, 90]

    def pack(self) -> bytes:
        # Azimuth: 0-360 mapped to uint16 (0-65535)
        az_comp = int((self.azimuth / 360.0) * 65535) & 0xFFFF
        # Elevation: -90 to 90 mapped to int8
        el_comp = int(self.elevation)
        # Clamp to int8 range
        el_comp = max(-128, min(127, el_comp))

        # Format: unsigned char, unsigned char, unsigned char, unsigned short, signed char
        # 'B B B H b' -> 1+1+1+2+1 = 6 bytes
        return struct.pack('<BBBHb',
                           MSG_TYPE_UPDATE,
                           self.node_id,
                           self.track_id,
                           az_comp,
                           el_comp)

def unpack_lora(data: bytes) -> tuple:
    """Helper to decode incoming LoRaWAN bytes."""
    msg_type = data[0]
    if msg_type == MSG_TYPE_ANNOUNCE and len(data) == 20:
        # NOTE: 1+1+4+4+4+2+2+2 = 20 bytes
        unpacked = struct.unpack('<BBfffhhh', data)
        return LoraAnnouncePacket(
            node_id=unpacked[1],
            lat=unpacked[2], lon=unpacked[3], alt=unpacked[4],
            roll_deg=unpacked[5]/100.0,
            pitch_deg=unpacked[6]/100.0,
            yaw_deg=unpacked[7]/100.0
        )
    elif msg_type == MSG_TYPE_UPDATE and len(data) == 6:
        unpacked = struct.unpack('<BBBHb', data)
        az = (unpacked[3] / 65535.0) * 360.0
        el = float(unpacked[4])
        return LoraUpdatePacket(
            node_id=unpacked[1],
            track_id=unpacked[2],
            azimuth=az,
            elevation=el
        )
    return None
