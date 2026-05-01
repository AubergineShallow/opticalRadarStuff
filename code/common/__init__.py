"""Common module - shared utilities across all components."""

from .constants import *
from .config import Config, load, get_config
from .protocol import (
    MotionVector,
    TelemetryPacket,
    CommandPacket,
    create_telemetry_packet,
    HEADER_SIZE,
    SIGNATURE_SIZE
)
from .network import send_packet

__all__ = [
    # Constants
    'SERVER_IP', 'UDP_PORT', 'MAX_PACKET_SIZE', 'VERSION',
    'MOTION_VECTOR_SIZE', 'TRACK_STATE_TENTATIVE', 'TRACK_STATE_CONFIRMED',
    'TRACK_STATE_LOST', 'TRACK_STATE_DELETED',
    'HEALTH_FLAG_GPS_OK', 'HEALTH_FLAG_CAMERA_OK', 'HEALTH_FLAG_IMU_OK',
    
    # Config
    'Config', 'load', 'get_config',
    
    # Protocol
    'MotionVector', 'TelemetryPacket', 'CommandPacket',
    'create_telemetry_packet', 'HEADER_SIZE', 'SIGNATURE_SIZE',

    # Network
    'send_packet',
]
