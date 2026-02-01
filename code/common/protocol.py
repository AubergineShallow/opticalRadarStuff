"""
protocol.py
PURPOSE: Defines how cameras talk to the main computer (Version 3).
"""

import struct
import time
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np

from .constants import VERSION, MOTION_VECTOR_SIZE



# Packet type identifiers
PACKET_TYPE_TELEMETRY = 0x01
PACKET_TYPE_COMMAND = 0x02
PACKET_TYPE_GROUND_TRUTH = 0x03
PACKET_TYPE_ANNOUNCE = 0x04

# Header size: 60 bytes for V3
HEADER_SIZE = 60
SIGNATURE_SIZE = 32


@dataclass
class MotionVector:
    """
    Single detection from camera.
    Packed size: 6 bytes (uint16 + int16 + uint8 + uint8)
    """
    azimuth: float      # [0, 360) degrees
    elevation: float    # [-90, 90] degrees
    intensity: int      # [0, 255]
    class_id: int       # [0, 255]
    
    def pack(self) -> bytes:
        """Pack to 6 bytes."""
        # Scale azimuth [0, 360) -> [0, 65535]
        az_raw = int((self.azimuth / 360.0) * 65535) & 0xFFFF
        # Scale elevation [-90, 90] -> [-32768, 32767]
        el_raw = int((self.elevation / 90.0) * 32767)
        el_raw = max(-32768, min(32767, el_raw))
        
        return struct.pack('>HhBB', az_raw, el_raw, 
                          self.intensity & 0xFF, self.class_id & 0xFF)
    
    @classmethod
    def unpack(cls, data: bytes) -> 'MotionVector':
        """Unpack from 6 bytes."""
        az_raw, el_raw, intensity, class_id = struct.unpack('>HhBB', data)
        
        azimuth = (az_raw / 65535.0) * 360.0
        elevation = (el_raw / 32767.0) * 90.0
        
        return cls(azimuth, elevation, intensity, class_id)


@dataclass
class AnnouncePacket:
    """
    Packet sent by node to announce capabilities.
    Features: FOV, Resolution, FPS.
    """
    version: int = VERSION
    packet_type: int = PACKET_TYPE_ANNOUNCE
    camera_id: str = ""
    timestamp: float = 0.0
    
    # Payload
    fov_horizontal: float = 60.0
    fov_vertical: float = 45.0
    resolution_width: int = 640
    resolution_height: int = 480
    fps: int = 30
    
    def pack(self) -> bytes:
        """Pack announce packet."""
        # Camera ID: 8 bytes (null-padded)
        cam_id_bytes = self.camera_id.encode('utf-8')[:8].ljust(8, b'\x00')
        
        # Header-like structure
        data = struct.pack(
            '>BB', self.version, self.packet_type
        )
        data += cam_id_bytes
        data += struct.pack('>d', self.timestamp)
        
        # Payload: ffHHB (float, float, ushort, ushort, uchar)
        # 4 + 4 + 2 + 2 + 1 = 13 bytes payload
        data += struct.pack(
            '>ffHHB',
            self.fov_horizontal,
            self.fov_vertical,
            self.resolution_width,
            self.resolution_height,
            self.fps
        )
        
        return data
    
    @classmethod
    def unpack(cls, data: bytes) -> 'AnnouncePacket':
        """Unpack announce packet."""
        offset = 0
        version, packet_type = struct.unpack_from('>BB', data, offset)
        offset += 2
        
        camera_id = data[offset:offset+8].rstrip(b'\x00').decode('utf-8')
        offset += 8
        
        timestamp, = struct.unpack_from('>d', data, offset)
        offset += 8
        
        fov_h, fov_v, w, h, fps = struct.unpack_from('>ffHHB', data, offset)
        
        return cls(
            version=version,
            packet_type=packet_type,
            camera_id=camera_id,
            timestamp=timestamp,
            fov_horizontal=fov_h,
            fov_vertical=fov_v,
            resolution_width=w,
            resolution_height=h,
            fps=fps
        )


@dataclass
class TelemetryPacket:
    """
    V3 Telemetry Packet from camera.
    Header: 60 bytes
    Body: N * 6 bytes (motion vectors)
    Signature: 32 bytes (optional, if security enabled)
    """
    # Header fields
    version: int = VERSION
    packet_type: int = PACKET_TYPE_TELEMETRY
    camera_id: str = ""
    sequence_number: int = 0
    timestamp: float = 0.0
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    orientation: tuple = (1.0, 0.0, 0.0, 0.0)  # Quaternion [w, x, y, z]
    health_flags: int = 0
    
    # Body
    vectors: List[MotionVector] = field(default_factory=list)
    
    # Security
    signature: Optional[bytes] = None
    
    def pack_header(self) -> bytes:
        """Pack 60-byte header."""
        # Camera ID: 8 bytes (null-padded)
        cam_id_bytes = self.camera_id.encode('utf-8')[:8].ljust(8, b'\x00')
        
        # Pack header fields (big-endian)
        header = struct.pack(
            '>BB',           # version (1) + packet_type (1)
            self.version,
            self.packet_type
        )
        header += cam_id_bytes  # camera_id (8)
        header += struct.pack(
            '>I',            # sequence_number (4)
            self.sequence_number
        )
        header += struct.pack(
            '>d',            # timestamp (8)
            self.timestamp
        )
        header += struct.pack(
            '>ddf',          # lat (8) + lon (8) + alt (4)
            self.latitude,
            self.longitude,
            self.altitude
        )
        header += struct.pack(
            '>ffff',         # orientation quaternion (16)
            self.orientation[0],
            self.orientation[1],
            self.orientation[2],
            self.orientation[3]
        )
        header += struct.pack(
            '>B',            # health_flags (1)
            self.health_flags
        )
        header += struct.pack(
            '>B',            # vector_count (1)
            len(self.vectors) & 0xFF
        )
        
        # Current: 2 + 8 + 4 + 8 + 8 + 8 + 4 + 16 + 1 + 1 = 60 bytes
        assert len(header) == HEADER_SIZE, f"Header size mismatch: {len(header)}"
        
        return header
    
    def pack(self, include_signature: bool = False) -> bytes:
        """Pack complete packet."""
        data = self.pack_header()
        
        for vec in self.vectors:
            data += vec.pack()
        
        if include_signature and self.signature:
            data += self.signature
        
        return data
    
    @classmethod
    def unpack(cls, data: bytes, has_signature: bool = False) -> 'TelemetryPacket':
        """Unpack packet from bytes."""
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Packet too short: {len(data)} < {HEADER_SIZE}")
        
        # Unpack header
        offset = 0
        version, packet_type = struct.unpack_from('>BB', data, offset)
        offset += 2
        
        camera_id = data[offset:offset+8].rstrip(b'\x00').decode('utf-8')
        offset += 8
        
        sequence_number, = struct.unpack_from('>I', data, offset)
        offset += 4
        
        timestamp, = struct.unpack_from('>d', data, offset)
        offset += 8
        
        latitude, longitude, altitude = struct.unpack_from('>ddf', data, offset)
        offset += 20
        
        qw, qx, qy, qz = struct.unpack_from('>ffff', data, offset)
        offset += 16
        
        health_flags, vector_count = struct.unpack_from('>BB', data, offset)
        offset += 2
        
        # Unpack vectors
        vectors = []
        for _ in range(vector_count):
            if offset + MOTION_VECTOR_SIZE > len(data):
                break
            vec = MotionVector.unpack(data[offset:offset+MOTION_VECTOR_SIZE])
            vectors.append(vec)
            offset += MOTION_VECTOR_SIZE
        
        # Extract signature if present
        signature = None
        if has_signature:
            remaining = len(data) - offset
            if remaining >= SIGNATURE_SIZE:
                signature = data[-SIGNATURE_SIZE:]
        
        return cls(
            version=version,
            packet_type=packet_type,
            camera_id=camera_id,
            sequence_number=sequence_number,
            timestamp=timestamp,
            latitude=latitude,
            longitude=longitude,
            altitude=altitude,
            orientation=(qw, qx, qy, qz),
            health_flags=health_flags,
            vectors=vectors,
            signature=signature
        )
    
    def get_data_for_signing(self) -> bytes:
        """Get packet data (header + vectors) for HMAC signing."""
        return self.pack(include_signature=False)


@dataclass
class CommandPacket:
    """Command packet from server to camera."""
    version: int = VERSION
    packet_type: int = PACKET_TYPE_COMMAND
    camera_id: str = ""
    command_type: int = 0
    payload: bytes = b""
    signature: Optional[bytes] = None
    
    # Command types
    CMD_CALIBRATION_UPDATE = 0x01
    CMD_CONFIG_UPDATE = 0x02
    CMD_RESTART = 0x03


def create_telemetry_packet(
    camera_id: str,
    latitude: float,
    longitude: float,
    altitude: float,
    orientation: tuple,
    vectors: List[MotionVector],
    sequence_number: int,
    health_flags: int = 0x07
) -> TelemetryPacket:
    """Helper to create a telemetry packet."""
    return TelemetryPacket(
        camera_id=camera_id,
        sequence_number=sequence_number,
        timestamp=time.time(),
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        orientation=orientation,
        health_flags=health_flags,
        vectors=vectors
    )
