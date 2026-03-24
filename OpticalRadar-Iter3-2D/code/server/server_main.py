"""
server_main.py
PURPOSE: Main server orchestrator for the optical radar system (2D fork).

NOTE: Run as module: python -m server.server_main
      Or use run_server.py launcher script.
"""

import time
import signal
import sys
import os
from typing import Optional, List
import numpy as np

# Add parent to path for absolute imports
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from common.config import load as load_config, Config
from common.protocol import TelemetryPacket, PACKET_TYPE_TELEMETRY, PACKET_TYPE_GROUND_TRUTH, PACKET_TYPE_ANNOUNCE, AnnouncePacket

# Use try/except for both module and direct execution support
try:
    from .udp_server import UDPServer
    from .voxel_grid import VoxelGrid, VoxelGridConfig
    from .ray_builder import RayBuilder
    from .calibration import Calibrator
    from .visualizer import Visualizer
    from .tracking import Tracker, Detection
    from .monitoring import (
        get_logger, configure_logger, get_metrics, 
        NodeHealthMonitor, Timer,
        METRIC_PACKETS_PROCESSED, METRIC_ACTIVE_TRACKS, METRIC_VOXEL_UPDATE_TIME
    )
    from .security import Authenticator
    from .validation import CalibrationValidator, GroundTruthValidator
    from .websocket_server import WebSocketBroadcaster
except ImportError:
    # Direct execution fallback
    from server.udp_server import UDPServer
    from server.voxel_grid import VoxelGrid, VoxelGridConfig
    from server.ray_builder import RayBuilder
    from server.calibration import Calibrator
    from server.visualizer import Visualizer
    from server.tracking import Tracker, Detection
    from server.monitoring import (
        get_logger, configure_logger, get_metrics, 
        NodeHealthMonitor, Timer,
        METRIC_PACKETS_PROCESSED, METRIC_ACTIVE_TRACKS, METRIC_VOXEL_UPDATE_TIME
    )
    from server.security import Authenticator
    from server.validation import CalibrationValidator, GroundTruthValidator
    from server.websocket_server import WebSocketBroadcaster


class OpticalRadarServer:
    """
    Main server orchestrating all subsystems (2D fork).

    Components:
        - UDP Server: Receive telemetry
        - Ray Builder: Convert packets to 2D rays
        - Grid: 2D accumulator for ray intersections
        - Tracker: Track persistent objects in 2D
        - Calibrator: Self-calibration
        - Monitoring: Health, metrics, logging
        - Security: Authentication
        - Validation: Quality assurance
        - Visualizer: 2D display
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        reference_lat: float = 0.0,
        reference_lon: float = 0.0,
        reference_alt: float = 0.0,
        headless: bool = False
    ):
        """
        Initialize server.

        Args:
            config_path: Path to config.yaml
            reference_lat: Reference latitude for ENU
            reference_lon: Reference longitude for ENU
            reference_alt: Reference altitude (used internally for GPS→ENU)
            headless: Run without visualization
        """
        # Load configuration
        self.config = load_config(config_path)
        self.headless = headless or self.config.system.headless

        # Configure logging
        self.logger = configure_logger(
            log_file=self.config.monitoring.log_file,
            log_level=self.config.monitoring.log_level
        )

        self.logger.info("system", "Initializing OpticalRadar server (2D mode)")

        # Initialize metrics
        self.metrics = get_metrics()

        # Security (optional)
        self.authenticator = None
        if self.config.security.enabled:
            try:
                self.authenticator = Authenticator(
                    key_file=self.config.security.key_file,
                    max_timestamp_drift_sec=self.config.security.auth_timeout_sec
                )
                self.logger.info("security", "Authentication enabled")
            except Exception as e:
                self.logger.warning("security", f"Auth disabled: {e}")

        # UDP Server
        self.udp_server = UDPServer(
            port=self.config.network.udp_port,
            max_packet_size=self.config.network.max_packet_size,
            authenticator=self.authenticator
        )

        # Ray Builder
        self.ray_builder = RayBuilder(
            reference_lat=reference_lat,
            reference_lon=reference_lon,
            reference_alt=reference_alt
        )

        # 2D Grid
        grid_config = VoxelGridConfig(
            width_m=self.config.grid.width_m,
            depth_m=self.config.grid.depth_m,
            resolution_m=self.config.grid.resolution_m,
            decay_rate=self.config.grid.decay_rate,
            hot_threshold=self.config.grid.hot_threshold,
            min_cameras=self.config.grid.min_cameras
        )
        self.voxel_grid = VoxelGrid(grid_config)

        # Tracker
        self.tracker = Tracker(
            distance_threshold=self.config.tracking.distance_threshold_m,
            min_hits_to_confirm=self.config.tracking.min_hits_to_confirm,
            max_misses_to_delete=self.config.tracking.max_misses_to_delete,
            max_tracks=self.config.tracking.max_tracks,
            q_process_noise=self.config.tracking.q_process_noise,
            r_measurement_noise=self.config.tracking.r_measurement_noise
        )

        # Validation
        self.calibration_validator = CalibrationValidator()
        self.ground_truth = GroundTruthValidator()

        # Calibrator
        self.calibrator = Calibrator(validator=self.calibration_validator)

        # Health Monitor
        self.node_health = NodeHealthMonitor(
            offline_timeout_sec=30.0,
            alert_callback=self._on_health_change
        )

        # WebSocket Server
        try:
            self.ws_server = WebSocketBroadcaster(port=5000)
            self.logger.info("system", "WebSocket server initialized")
        except Exception as e:
            self.logger.error("system", f"Failed to init WebSocket: {e}")
            self.ws_server = None

        # Visualizer
        self.visualizer = None
        if not self.headless:
            self.visualizer = Visualizer()

        # State
        self._running = False
        self._frame_count = 0
        self._start_time = time.time()
        self._last_frame_time = 0.0
        self._fps = 0.0

    def _on_health_change(self, node_id: str, old_status, new_status) -> None:
        """Handle node health status change."""
        self.logger.warning(
            "health", 
            f"Node {node_id} status changed: {old_status.value} -> {new_status.value}"
        )

    def start(self) -> None:
        """Start the server."""
        self.logger.info("system", "Starting server")

        # Start UDP server
        self.udp_server.start()

        # Start WebSocket server
        if self.ws_server:
            self.ws_server.start()

        # Setup visualizer
        if self.visualizer:
            self.visualizer.setup()

        self._running = True

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger.info("system", f"Server running on port {self.config.network.udp_port}")

    def stop(self) -> None:
        """Stop the server."""
        self.logger.info("system", "Stopping server")

        self._running = False
        self.udp_server.stop()

        if self.ws_server:
            self.ws_server.stop()

        if self.visualizer:
            self.visualizer.close()

    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals."""
        self.stop()

    def process_frame(self) -> None:
        """Process one frame of telemetry."""
        self._frame_count += 1

        # Decay grid
        self.voxel_grid.decay()

        # Get all available packets
        packets = self.udp_server.get_packets(max_count=100)

        for received in packets:
            # DEBUG: Log sender IP to file for identification
            if received.sender_ip != "127.0.0.1":
                try:
                    with open("node_ips.log", "a") as f:
                        f.write(f"{time.ctime()} | {received.sender_ip} | {getattr(received.packet, 'camera_id', '?')}\n")
                except:
                    pass
            self._process_packet(received.packet, received.receive_time, received.sender_ip)

        # Extract detections from grid
        with Timer(METRIC_VOXEL_UPDATE_TIME):
            detection_positions = self.voxel_grid.get_detections()

        # Convert to Detection objects
        detections = [
            Detection(position=pos, confidence=1.0, timestamp=time.time())
            for pos in detection_positions
        ]

        # Update tracker
        result = self.tracker.update(detections)

        # Update metrics
        self.metrics.set_gauge(METRIC_ACTIVE_TRACKS, len(result.tracks))
        self.metrics.increment_counter(METRIC_PACKETS_PROCESSED, len(packets))

        # Run calibration and apply corrections to ray builder
        cal_results = self.calibrator.process()
        for cal_result in cal_results:
            if cal_result.approved:
                self.ray_builder.set_calibration_offset(
                    cal_result.camera_id,
                    cal_result.correction_quaternion
                )

        # Track FPS
        now = time.time()
        if self._last_frame_time > 0:
            dt = now - self._last_frame_time
            if dt > 0:
                alpha = 0.1
                self._fps = alpha * (1.0 / dt) + (1 - alpha) * self._fps
        self._last_frame_time = now

        # Update visualizer
        if self.visualizer:
            self._update_visualizer(detection_positions)

        # Broadcast state via WebSocket
        if self.ws_server:
            # Cache grid stats once per frame
            grid_stats = self.voxel_grid.get_stats()

            # DEBUG
            if self._frame_count % 30 == 0:
                # Log all known node IPs in heartbeat
                node_ips = [r.ip_address for r in self.node_health.get_all_nodes().values()]
                print(f"[Server] FPS: {self._fps:.1f} | Active Tracks: {len(result.tracks)} | Hot Voxels: {grid_stats['hot_count_verified']} | Nodes: {node_ips}")
            
            self._broadcast_state(grid_stats)

    def _broadcast_state(self, grid_stats: dict) -> None:
        """Broadcast system state to UI (2D positions)."""
        # 1. System Status
        self.ws_server.broadcast("SYSTEM_STATUS", {
            "server_fps": round(self._fps, 1),
            "total_tracks": len(self.tracker.get_confirmed_tracks()),
            "total_cells": grid_stats['hot_count_verified'],
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "cpu_percent": 0.0,
            "memory_percent": 0.0
        })

        # 2. Tracks (2D positions)
        tracks = []
        for track in self.tracker.get_confirmed_tracks():
            vel = track.velocity
            pos = track.position
            tracks.append({
                "track_id": track.track_id,
                "state": int(track.state),
                "position": [float(pos[0]), float(pos[1])],
                "velocity": [float(vel[0]), float(vel[1])],
                "covariance": [],
                "first_seen": track.created_at,
                "last_seen": track.last_update,
                "hit_count": track.hits,
                "confidence": track.confidence,
                "predicted_next": [0, 0]
            })
        self.ws_server.broadcast("TRACK_UPDATE", tracks)

        # 3. Nodes (with config)
        nodes = []
        for node_id, record in self.node_health.get_all_nodes().items():
            status_val = 3
            rec_status = record.get_status().value
            if rec_status == "healthy": status_val = 0
            elif rec_status == "degraded": status_val = 1
            elif rec_status == "unhealthy": status_val = 2
            elif rec_status == "offline": status_val = 3

            # Parse hardware flags (PIR, Touch, Temp)
            has_temp = bool(record.health_flags & 0x20)
            has_touch = bool(record.health_flags & 0x10)
            has_pir = bool(record.health_flags & 0x08)

            # Map temp presence to a generic flag or value if applicable
            nodes.append({
                "node_id": node_id,
                "status": status_val,
                "last_seen": record.last_packet_time,
                "fps": record.packets_per_second,
                "cpu_usage": 0.0,
                "temp_c": 25.0 if has_temp else 0.0, # Placeholder 25.0 if sensor is connected, otherwise 0
                "ip_address": record.ip_address,
                "location": [0, 0],
                "mode": record.mode,
                "config": {
                    **(record.sensor_config or {}),
                    "pir": has_pir,
                    "touch": has_touch
                }
            })
        self.ws_server.broadcast("NODE_UPDATE", nodes)

    def _process_packet(self, packet: object, receive_time: float, ip_address: str = "unknown") -> None:
        """Process a single telemetry packet based on its type."""
        if packet.packet_type == PACKET_TYPE_GROUND_TRUTH:
            self._process_ground_truth_packet(packet)
            return

        if packet.packet_type == PACKET_TYPE_ANNOUNCE:
            self._process_announce_packet(packet, ip_address)
            return

        if packet.packet_type == PACKET_TYPE_TELEMETRY:
            self._process_telemetry_packet(packet, receive_time, ip_address)

    def _process_announce_packet(self, packet: AnnouncePacket, ip_address: str = "unknown") -> None:
        """Process announce packet."""
        config = {
            "fov": packet.fov_horizontal,
            "fov_v": packet.fov_vertical,
            "resolution": [packet.resolution_width, packet.resolution_height],
            "fps": packet.fps
        }
        self.node_health.update_node_config(packet.camera_id, config)
        
        # Also update IP since Announce packets might be received independently
        if ip_address != "unknown":
            self.node_health.record_packet(
                packet.camera_id,
                packet.timestamp,
                0,
                0,
                time.time(),
                0, # Default mode
                ip_address
            )
            
        self.logger.info("network", f"Received announcement from {packet.camera_id}")

    def _process_ground_truth_packet(self, packet: TelemetryPacket) -> None:
        """Process ground truth packet for validation."""
        timestamp = packet.timestamp
        camera_id = packet.camera_id

        # Decompose packet into the 6-argument form expected by build_rays_from_packet
        vectors = [
            (v.azimuth, v.elevation, v.intensity)
            for v in packet.vectors
        ]

        rays = self.ray_builder.build_rays_from_packet(
            camera_id,
            packet.latitude,
            packet.longitude,
            packet.altitude,
            packet.orientation,
            vectors
        )

        for i, ray in enumerate(rays):
            # Project ground-truth position along 2D ray
            self.ground_truth.add_ground_truth(
                object_id=f"gt_{camera_id}_{i}",
                position=ray.origin + ray.direction * 100.0,
                timestamp=timestamp
            )

        self.logger.debug("validation", f"Received ground truth from {camera_id}")

    def _process_telemetry_packet(self, packet: TelemetryPacket, receive_time: float, ip_address: str = "unknown") -> None:
        """Process telemetry packet from camera."""
        # Update node health
        self.node_health.record_packet(
            packet.camera_id,
            packet.timestamp,
            packet.sequence_number,
            packet.health_flags,
            receive_time,
            packet.mode,
            ip_address
        )

        # Build rays from vectors
        vectors = [
            (v.azimuth, v.elevation, v.intensity)
            for v in packet.vectors
        ]

        rays = self.ray_builder.build_rays_from_packet(
            packet.camera_id,
            packet.latitude,
            packet.longitude,
            packet.altitude,
            packet.orientation,
            vectors
        )

        # Add all rays to grid (with camera_id for ghost-track prevention)
        for ray in rays:
            self.voxel_grid.add_ray(
                ray.origin,
                ray.direction,
                ray.intensity,
                camera_id=packet.camera_id
            )

        # Use confirmed tracks for calibration
        confirmed_tracks = self.tracker.get_confirmed_tracks()

        if confirmed_tracks and rays:
            track_positions = np.array([t.position for t in confirmed_tracks])

            for ray in rays:
                best_position = self._find_best_matching_cell(
                    ray.origin, ray.direction, track_positions
                )

                if best_position is not None:
                    self.calibrator.add_observation(
                        packet.camera_id,
                        ray.direction,
                        best_position,
                        ray.origin
                    )

    def _find_best_matching_cell(
        self,
        ray_origin: np.ndarray,
        ray_direction: np.ndarray,
        candidate_positions: np.ndarray
    ) -> Optional[np.ndarray]:
        """
        Find the 2D position that best matches a ray's direction.

        Uses ray-point distance in 2D to find the closest position.
        """
        if len(candidate_positions) == 0:
            return None

        # Ensure 2D
        origin_2d = ray_origin[:2]
        dir_2d = ray_direction[:2]
        dir_norm = np.linalg.norm(dir_2d)
        if dir_norm < 1e-12:
            return None
        dir_2d = dir_2d / dir_norm

        candidates_2d = np.array([p[:2] for p in candidate_positions])

        to_points = candidates_2d - origin_2d
        projections = np.dot(to_points, dir_2d)

        valid_mask = projections > 0
        if not np.any(valid_mask):
            return None

        closest_on_ray = origin_2d + projections[:, np.newaxis] * dir_2d
        distances = np.linalg.norm(candidates_2d - closest_on_ray, axis=1)

        distances[~valid_mask] = float('inf')

        min_idx = np.argmin(distances)
        if distances[min_idx] < 10.0:
            return candidate_positions[min_idx]

        return None

    def _update_visualizer(self, detections: list = None) -> None:
        """Update the visualization."""
        if not self.visualizer:
            return

        if detections is None:
            detections = self.voxel_grid.get_detections()

        cameras = [
            (cam_id, self.ray_builder.get_camera_position(cam_id))
            for cam_id in self.ray_builder.get_all_cameras()
        ]
        cameras = [(cid, pos) for cid, pos in cameras if pos is not None]

        tracks = [
            (track.track_id, track.position)
            for track in self.tracker.get_confirmed_tracks()
        ]

        hot_cells = [
            (v.center, v.heat)
            for v in self.voxel_grid.get_hot_cells()[:100]
        ]

        self.visualizer.update(
            detections=detections,
            camera_positions=cameras,
            tracks=tracks,
            hot_voxels=hot_cells
        )

    def run(self, target_fps: float = 30.0) -> None:
        """
        Main run loop.

        Args:
            target_fps: Target frames per second
        """
        self.start()

        frame_time = 1.0 / target_fps

        while self._running:
            frame_start = time.time()

            self.process_frame()

            elapsed = time.time() - frame_start
            sleep_time = frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        self.logger.info("system", "Server stopped")


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="OpticalRadar Server (2D)")
    parser.add_argument("--config", "-c", help="Config file path")
    parser.add_argument("--port", "-p", type=int, help="UDP port")
    parser.add_argument("--ref-lat", type=float, default=0.0, help="Reference latitude")
    parser.add_argument("--ref-lon", type=float, default=0.0, help="Reference longitude")
    parser.add_argument("--headless", action="store_true", help="Run without visualization")
    parser.add_argument("--ref-alt", type=float, default=0.0, help="Reference altitude (m)")

    args = parser.parse_args()

    server = OpticalRadarServer(
        config_path=args.config,
        reference_lat=args.ref_lat,
        reference_lon=args.ref_lon,
        reference_alt=args.ref_alt,
        headless=args.headless
    )

    server.run()


if __name__ == "__main__":
    main()
