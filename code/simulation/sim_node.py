"""
sim_node.py
PURPOSE: Simulated camera node for testing without real hardware.
"""

import time
import socket
import math
import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass

import sys
import os
_parent = os.path.dirname(os.path.dirname(__file__))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from common.constants import UDP_PORT, TARGET_FPS, PROTOCOL_VERSION
from common.protocol import TelemetryPacket, MotionVector as ProtocolMotionVector

from .sim_utils import enu_to_azel, add_noise


@dataclass
class SimTarget:
    """Simulated target."""
    target_id: str
    position: np.ndarray  # [e, n, u] ENU
    velocity: np.ndarray = None  # [ve, vn, vu] m/s
    class_id: int = 0
    
    def __post_init__(self):
        if self.velocity is None:
            self.velocity = np.zeros(3)


@dataclass
class SimCameraConfig:
    """Simulated camera configuration."""
    camera_id: str
    position: np.ndarray  # [e, n, u] ENU
    orientation: Tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
    fov_horizontal: float = 90.0
    fov_vertical: float = 60.0
    max_range: float = 500.0
    detection_noise_deg: float = 0.5
    
    # GPS position (for protocol)
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0


class SimNode:
    """
    Simulated camera node.
    
    Takes list of targets and simulates what a camera would see,
    sending appropriate telemetry packets.
    """
    
    def __init__(
        self,
        config: SimCameraConfig,
        server_address: str = "127.0.0.1",
        server_port: int = UDP_PORT
    ):
        """
        Initialize simulated node.
        
        Args:
            config: Camera configuration
            server_address: Server IP
            server_port: Server UDP port
        """
        self.config = config
        self.server_address = server_address
        self.server_port = server_port
        
        self._socket: Optional[socket.socket] = None
        self._sequence = 0
        self._running = False
        
        # Targets
        self._targets: List[SimTarget] = []
    
    def add_target(self, target: SimTarget) -> None:
        """Add a target to the simulation."""
        self._targets.append(target)
    
    def clear_targets(self) -> None:
        """Remove all targets."""
        self._targets.clear()
    
    def start(self) -> bool:
        """Start the simulated node."""
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._running = True
            return True
        except Exception as e:
            print(f"SimNode start failed: {e}")
            return False
    
    def stop(self) -> None:
        """Stop the simulated node."""
        self._running = False
        if self._socket:
            self._socket.close()
            self._socket = None
    
    def update_targets(self, dt: float) -> None:
        """
        Update target positions based on velocity.
        
        Args:
            dt: Time step in seconds
        """
        for target in self._targets:
            target.position += target.velocity * dt
    
    def detect_targets(self) -> List[Tuple[SimTarget, float, float]]:
        """
        Simulate target detection.
        
        Returns:
            List of (target, azimuth, elevation) for visible targets
        """
        detections = []
        
        for target in self._targets:
            # Calculate angles to target
            azimuth, elevation = enu_to_azel(
                target.position[0], target.position[1], target.position[2],
                self.config.position[0], self.config.position[1], self.config.position[2]
            )
            
            # Check distance
            distance = np.linalg.norm(target.position - self.config.position)
            if distance > self.config.max_range:
                continue
            
            # Check FOV (simplified - assumes camera pointing North, level)
            # Real implementation would apply camera orientation
            rel_az = azimuth % 360
            if rel_az > self.config.fov_horizontal / 2 and rel_az < 360 - self.config.fov_horizontal / 2:
                continue
            
            if abs(elevation) > self.config.fov_vertical / 2:
                continue
            
            # Add detection noise
            noisy_az = add_noise(azimuth, self.config.detection_noise_deg)
            noisy_el = add_noise(elevation, self.config.detection_noise_deg)
            
            detections.append((target, noisy_az, noisy_el))
        
        return detections
    
    def process_frame(self) -> bool:
        """
        Process one simulation frame and send packet.
        
        Returns:
            True if packet sent
        """
        # Detect targets
        detections = self.detect_targets()
        
        # Build motion vectors
        vectors = []
        for target, azimuth, elevation in detections:
            vectors.append(ProtocolMotionVector(
                azimuth=azimuth,
                elevation=elevation,
                intensity=200,
                class_id=target.class_id
            ))
        
        # Build packet
        packet = TelemetryPacket(
            version=PROTOCOL_VERSION,
            camera_id=self.config.camera_id,
            timestamp=time.time(),
            sequence_number=self._sequence,
            latitude=self.config.latitude,
            longitude=self.config.longitude,
            altitude=self.config.altitude,
            orientation=self.config.orientation,
            health_flags=0x07,  # All healthy
            vectors=vectors
        )
        
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        
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
    
    def run(
        self,
        duration: float = 60.0,
        target_fps: float = TARGET_FPS
    ) -> None:
        """
        Run simulation loop.
        
        Args:
            duration: How long to run (seconds)
            target_fps: Target frame rate
        """
        if not self.start():
            print("Failed to start SimNode")
            return
        
        frame_time = 1.0 / target_fps
        start_time = time.time()
        
        while self._running and (time.time() - start_time) < duration:
            frame_start = time.time()
            
            self.update_targets(frame_time)
            self.process_frame()
            
            elapsed = time.time() - frame_start
            sleep_time = frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        self.stop()


def create_demo_simulation(
    num_cameras: int = 4,
    num_targets: int = 2,
    arena_size: float = 100.0
) -> List[SimNode]:
    """
    Create a demo simulation with cameras around an arena.
    
    Args:
        num_cameras: Number of cameras
        num_targets: Number of moving targets
        arena_size: Size of the arena
    
    Returns:
        List of SimNode instances
    """
    nodes = []
    
    # Place cameras in a circle
    for i in range(num_cameras):
        angle = (2 * math.pi * i) / num_cameras
        pos = np.array([
            arena_size * math.cos(angle),
            arena_size * math.sin(angle),
            2.0  # 2m height
        ])
        
        config = SimCameraConfig(
            camera_id=f"sim{i+1:02d}",
            position=pos,
            latitude=37.7749 + pos[1] * 0.00001,
            longitude=-122.4194 + pos[0] * 0.00001,
            altitude=10.0 + pos[2]
        )
        
        node = SimNode(config)
        
        # Add shared targets to all nodes
        for j in range(num_targets):
            target_pos = np.array([
                np.random.uniform(-arena_size/2, arena_size/2),
                np.random.uniform(-arena_size/2, arena_size/2),
                np.random.uniform(20, 50)
            ])
            target_vel = np.array([
                np.random.uniform(-5, 5),
                np.random.uniform(-5, 5),
                0
            ])
            
            node.add_target(SimTarget(
                target_id=f"target{j+1:02d}",
                position=target_pos.copy(),
                velocity=target_vel.copy()
            ))
        
        nodes.append(node)
    
    return nodes
