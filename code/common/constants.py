"""
constants.py
PURPOSE: Stores fixed settings for the system.
"""

# Server Address
SERVER_IP = "0.0.0.0"
UDP_PORT = 5005

# Message Size Limit
MAX_PACKET_SIZE = 512

# Version Number (Protocol V3)
VERSION = 3
PROTOCOL_VERSION = VERSION  # Alias

# Target frame rate
TARGET_FPS = 30

# Performance Targets (from IMPLEMENTATION_CONVENTIONS)
MAX_FRAME_TIME_MS = 50
MAX_VOXEL_UPDATE_MS = 10
MAX_TRACKING_MS = 5

# Motion Vector Constants
MOTION_VECTOR_SIZE = 6  # bytes (uint16 + int16 + uint8 + uint8)

# Track States
TRACK_STATE_TENTATIVE = 0
TRACK_STATE_CONFIRMED = 1
TRACK_STATE_LOST = 2
TRACK_STATE_DELETED = 3

# Health Flags
HEALTH_FLAG_GPS_OK = 0x01
HEALTH_FLAG_CAMERA_OK = 0x02
HEALTH_FLAG_IMU_OK = 0x04
