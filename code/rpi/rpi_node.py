"""
rpi_node.py
PURPOSE: Main orchestrator for Raspberry Pi camera node.
"""

import time
import socket
import signal
import sys
import os
from typing import Optional

_parent = os.path.dirname(os.path.dirname(__file__))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from common.config import load as load_config
from common.constants import UDP_PORT, TARGET_FPS, PROTOCOL_VERSION
from common.protocol import TelemetryPacket, MotionVector as ProtocolMotionVector, AnnouncePacket

from .vision import VisionSystem, VisionConfig
from .gps import GPSReader
from .imu import IMUReader


class RPiNode:
    """
    Main camera node orchestrator.
    
    Workflow:
        1. Capture frame (Vision)
        2. Detect motion (Vision)
        3. Get position (GPS)
        4. Get orientation (IMU)
        5. Pack and send packet (Network)
        
    Health Flags:
        bit 0: GPS fix
        bit 1: Camera OK
        bit 2: IMU OK
    """
    
    def __init__(
        self,
        camera_id: str,
        server_address: str = "127.0.0.1",
        server_port: int = UDP_PORT,
        config_path: Optional[str] = None,
        mock: bool = False
    ):
        """
        Initialize camera node.
        
        Args:
            camera_id: Unique camera identifier
            server_address: Server IP address
            server_port: Server UDP port
            config_path: Path to config.yaml
            mock: Use mock sensors
        """
        self.camera_id = camera_id
        self.server_address = server_address
        self.server_port = server_port
        self.mock = mock
        
        # Load config
        self.config = load_config(config_path)
        
        # Initialize components
        self.vision = VisionSystem(VisionConfig(
            fps=TARGET_FPS
        ))
        
        self.gps = GPSReader(port=self.config.gps.port, mock=mock)
        
        self.imu = IMUReader(i2c_address=self.config.imu.i2c_address, mock=mock)
        
        # Network
        self._socket: Optional[socket.socket] = None
        
        # State
        self._running = False
        self._sequence = 0
        self._frame_count = 0
        self._last_announce_time = 0.0
    
    def start(self) -> bool:
        """
        Start all components.
        
        Returns:
            True if successful
        """
        print(f"Starting RPi Node: {self.camera_id}")
        
        # Start sensors
        if not self.vision.start():
            print("Warning: Vision system failed to start")
        
        if not self.gps.start():
            print("Warning: GPS failed to start")
        
        if not self.imu.start():
            print("Warning: IMU failed to start")
        
        # Create UDP socket
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception as e:
            print(f"Socket creation failed: {e}")
            return False
        
        self._running = True
        
        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        print(f"Node started, sending to {self.server_address}:{self.server_port}")
        
        # Send initial burst of announcements
        for _ in range(3):
            self._send_announce()
            time.sleep(0.1)
            
        return True
    
    def stop(self) -> None:
        """Stop all components."""
        print("Stopping RPi Node")
        
        self._running = False
        
        self.vision.stop()
        self.gps.stop()
        self.imu.stop()
        
        if self._socket:
            self._socket.close()
            self._socket = None
    
    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals."""
        self.stop()
    
    def _get_health_flags(self) -> int:
        """Calculate health flags byte."""
        flags = 0
        
        # Bit 0: GPS signal/fix
        if self.gps.has_fix():
            flags |= 0x01
        
        # Bit 1: Camera OK
        if self.vision.is_running:
            flags |= 0x02
        
        # Bit 2: IMU OK
        if self.imu.is_running:
            flags |= 0x04
        
        return flags
        
    def _send_announce(self) -> bool:
        """Send announce packet with configuration."""
        if not self._socket:
            return False
            
        try:
            packet = AnnouncePacket(
                camera_id=self.camera_id,
                timestamp=time.time(),
                fov_horizontal=self.vision.config.horizontal_fov,
                fov_vertical=self.vision.config.vertical_fov,
                resolution_width=self.vision.config.resolution[0],
                resolution_height=self.vision.config.resolution[1],
                fps=self.vision.config.fps
            )
            
            data = packet.pack()
            self._socket.sendto(data, (self.server_address, self.server_port))
            return True
        except Exception as e:
            print(f"Announce failed: {e}")
            return False
    
    def process_frame(self) -> bool:
        """
        Process one frame.
        
        Returns:
            True if packet was sent
        """
        self._frame_count += 1
        
        # 1. Capture and detect motion
        frame, vectors = self.vision.get_frame_and_vectors()
        
        # 2. Get GPS position
        gps_fix = self.gps.get_fix()
        if gps_fix:
            lat, lon, alt = gps_fix.latitude, gps_fix.longitude, gps_fix.altitude
        else:
            lat, lon, alt = 0.0, 0.0, 0.0
        
        # 3. Get IMU orientation
        orientation = self.imu.get_quaternion()
        if orientation is None:
            orientation = (1.0, 0.0, 0.0, 0.0)
        
        # 4. Build packet
        protocol_vectors = []
        for v in vectors:
            protocol_vectors.append(ProtocolMotionVector(
                azimuth=v.azimuth,
                elevation=v.elevation,
                intensity=v.intensity,
                class_id=v.class_id
            ))
        
        packet = TelemetryPacket(
            version=PROTOCOL_VERSION,
            camera_id=self.camera_id,
            timestamp=time.time(),
            sequence_number=self._sequence,
            latitude=lat,
            longitude=lon,
            altitude=alt,
            orientation=orientation,
            health_flags=self._get_health_flags(),
            vectors=protocol_vectors
        )
        
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        
        # 5. Send packet
        return self._send_packet(packet)
    
    def _send_packet(self, packet: TelemetryPacket) -> bool:
        """Send packet to server."""
        if not self._socket:
            return False
        
        try:
            data = packet.pack()
            self._socket.sendto(data, (self.server_address, self.server_port))
            return True
        except Exception as e:
            print(f"Send failed: {e}")
            return False
    
    def run(self, target_fps: float = TARGET_FPS) -> None:
        """
        Main run loop.
        
        Args:
            target_fps: Target frames per second
        """
        if not self.start():
            print("Failed to start node")
            return
        
        frame_time = 1.0 / target_fps
        
        while self._running:
            frame_start = time.time()
            
            # Periodic announcement (every 5 seconds)
            if time.time() - self._last_announce_time > 5.0:
                self._send_announce()
                self._last_announce_time = time.time()
            
            self.process_frame()
            
            # Rate limiting
            elapsed = time.time() - frame_start
            sleep_time = frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        print("Node stopped")
    
    def get_stats(self) -> dict:
        """Get node statistics."""
        gps_fix = self.gps.get_fix()
        orientation = self.imu.get_orientation()
        
        return {
            'camera_id': self.camera_id,
            'frame_count': self._frame_count,
            'sequence': self._sequence,
            'gps_fix': gps_fix.fix_quality if gps_fix else 0,
            'satellites': gps_fix.satellites if gps_fix else 0,
            'roll': orientation.roll if orientation else 0,
            'pitch': orientation.pitch if orientation else 0,
            'yaw': orientation.yaw if orientation else 0,
            'health_flags': self._get_health_flags()
        }


def main():
    """Entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="OpticalRadar Camera Node")
    parser.add_argument("--id", "-i", default="cam01", help="Camera ID")
    parser.add_argument("--server", "-s", default="127.0.0.1", help="Server address")
    parser.add_argument("--port", "-p", type=int, default=UDP_PORT, help="Server port")
    parser.add_argument("--config", "-c", help="Config file path")
    parser.add_argument("--mock", "-m", action="store_true", help="Use mock sensors")
    
    args = parser.parse_args()
    
    node = RPiNode(
        camera_id=args.id,
        server_address=args.server,
        server_port=args.port,
        config_path=args.config,
        mock=args.mock
    )
    
    node.run()


if __name__ == "__main__":
    main()
