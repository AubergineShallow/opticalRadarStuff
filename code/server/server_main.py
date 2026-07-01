"""
server_main.py
PURPOSE: Main server orchestrator for the optical radar system.

NOTE: Run as module: python -m server.server_main
      Or use run_server.py launcher script.
"""

import time
import signal
import sys
import os
from typing import Optional, List, Tuple
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
    from .foxglove_broadcaster import FoxgloveBroadcaster
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
    from server.foxglove_broadcaster import FoxgloveBroadcaster


class OpticalRadarServer:
    """
    Main server orchestrating all subsystems.
    
    Components:
        - UDP Server: Receive telemetry
        - Ray Builder: Convert packets to rays
        - Voxel Grid: Accumulate ray intersections
        - Tracker: Track persistent objects
        - Calibrator: Self-calibration
        - Monitoring: Health, metrics, logging
        - Security: Authentication
        - Validation: Quality assurance
        - Visualizer: 3D display
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
            reference_alt: Reference altitude for ENU (meters above sea level)
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
        
        self.logger.info("system", "Initializing OpticalRadar server")
        
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
        
        # Voxel Grid
        grid_config = VoxelGridConfig(
            width_m=self.config.grid.width_m,
            depth_m=self.config.grid.depth_m,
            height_m=self.config.grid.height_m,
            resolution_m=self.config.grid.resolution_m,
            decay_rate=self.config.grid.decay_rate,
            hot_threshold=self.config.grid.hot_threshold
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

        # Foxglove Broadcaster
        fg_config = getattr(self.config, 'foxglove', None)
        fg_enabled = fg_config.enabled if fg_config else False
        fg_port = fg_config.port if fg_config else 8765
        self.fg_server = FoxgloveBroadcaster(port=fg_port, enabled=fg_enabled)
        
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

        self.fg_server.start()
        
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

        self.fg_server.stop()
        
        if self.visualizer:
            self.visualizer.close()
    
    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals."""
        self.stop()
    
    def process_frame(self) -> None:
        """Process one frame of telemetry."""
        self._frame_count += 1
        
        # Decay voxel grid
        self.voxel_grid.decay()
        
        # Get all available packets
        packets = self.udp_server.get_packets(max_count=100)
        
        for received in packets:
            self._process_packet(received.packet, received.receive_time)
        
        # Extract detections from voxel grid
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
        # Publish scene to Foxglove
        self.fg_server.publish_scene(
            cluster_id="global",
            tracks=self.tracker.get_confirmed_tracks(),
            hot_voxels=self.voxel_grid.get_hot_voxels(),
            rays=getattr(self, '_last_rays', [])
        )
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
        
        # Update visualizer (reuse detection_positions to avoid redundant computation)
        if self.visualizer:
            self._update_visualizer(detection_positions)
            
        # Broadcast state via WebSocket
        if self.ws_server:
            self._broadcast_state()
    
    def _broadcast_state(self) -> None:
        """Broadcast system state to UI."""
        # 1. System Status
        grid_stats = self.voxel_grid.get_stats()

        status_data = {
            "server_fps": round(self._fps, 1),
            "total_tracks": len(self.tracker.get_confirmed_tracks()),
            "total_voxels": grid_stats['hot_count'],
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "cpu_percent": 0.0,
            "memory_percent": 0.0
        }

        self.ws_server.broadcast("SYSTEM_STATUS", status_data)
        self.fg_server.publish_system_status(status_data)
        
        # 2. Tracks (consolidated)
        tracks = []
        for track in self.tracker.get_confirmed_tracks():
            vel = track.velocity
            tracks.append({
                "track_id": track.track_id,
                "state": int(track.state),
                "position": [track.position[0], track.position[1], track.position[2]],
                "velocity": [float(vel[0]), float(vel[1]), float(vel[2])],
                "covariance": [],
                "first_seen": track.created_at,
                "last_seen": track.last_update,
                "hit_count": track.hits,
                "confidence": track.confidence,
                "predicted_next": [0,0,0],
                "physical_size": float(getattr(track, 'physical_size', 0.0))
            })
        self.ws_server.broadcast("TRACK_UPDATE", tracks)
        
        # 3. Nodes (with config)
        nodes = []
        for node_id, record in self.node_health.get_all_nodes().items():
            # Map status string to integer
            # HEALTHY=0, DEGRADED=1, UNHEALTHY=2, OFFLINE=3
            status_val = 3
            rec_status = record.get_status().value
            if rec_status == "healthy": status_val = 0
            elif rec_status == "degraded": status_val = 1
            elif rec_status == "unhealthy": status_val = 2
            elif rec_status == "offline": status_val = 3
            
            nodes.append({
                "node_id": node_id,
                "status": status_val,
                "last_seen": record.last_packet_time,
                "fps": record.packets_per_second,
                "cpu_usage": 0.0,
                "temp_c": 0.0,
                "ip_address": "unknown",
                "location": [0,0,0], # TODO: Link to ray_builder camera positions
                # Extra config fields can be merged if frontend supports them
                "config": record.sensor_config
            })
        self.ws_server.broadcast("NODE_UPDATE", nodes)
        self.fg_server.publish_node_update({"nodes": nodes})

        # 4. Clusters (placeholder for compatibility)
        cluster_data = {"clusters": []}
        self.fg_server.publish_clusters(cluster_data)

    def _process_packet(self, packet: object, receive_time: float) -> None:
        """Process a single telemetry packet based on its type."""
        # Route based on packet type
        if packet.packet_type == PACKET_TYPE_GROUND_TRUTH:
            self._process_ground_truth_packet(packet)
            return
            
        if packet.packet_type == PACKET_TYPE_ANNOUNCE:
            self._process_announce_packet(packet)
            return
        
        # Default: process as telemetry
        if packet.packet_type == PACKET_TYPE_TELEMETRY:
            self._process_telemetry_packet(packet, receive_time)

    def _process_announce_packet(self, packet: AnnouncePacket) -> None:
        """Process announce packet."""
        config = {
            "fov": packet.fov_horizontal,
            "fov_v": packet.fov_vertical,
            "resolution": [packet.resolution_width, packet.resolution_height],
            "fps": packet.fps
        }
        self.node_health.update_node_config(packet.camera_id, config)
        self.logger.info("network", f"Received announcement from {packet.camera_id}")
    
    def _process_ground_truth_packet(self, packet: TelemetryPacket) -> None:
        """Process ground truth packet for validation.
        
        Ground truth packets use the same telemetry format but are tagged as
        PACKET_TYPE_GROUND_TRUTH. The vectors represent known target positions
        encoded as azimuth/elevation from the camera. We reconstruct the 3D
        ray and register the direction with the ground truth validator.
        """
        timestamp = packet.timestamp
        camera_id = packet.camera_id
        
        # Build rays from the ground truth vectors (same pipeline as telemetry)
        rays = self.ray_builder.build_rays_from_packet(packet)
        
        for i, ray in enumerate(rays):
            # Use the ray origin + direction to register the ground truth position
            # For ground truth, we assume the vector points at the actual object
            self.ground_truth.add_ground_truth(
                object_id=f"gt_{camera_id}_{i}",
                position=ray.origin + ray.direction * 100.0,  # Project along ray
                timestamp=timestamp
            )
        
        self.logger.debug("validation", f"Received ground truth from {packet.camera_id}")
    
    def _process_telemetry_packet(self, packet: TelemetryPacket, receive_time: float) -> None:
        """Process telemetry packet from camera."""
        # Update node health
        self.node_health.record_packet(
            packet.camera_id,
            packet.timestamp,
            packet.sequence_number,
            packet.health_flags
        )
        
        # Publish location to Foxglove
        self.fg_server.publish_node_location(
            packet.camera_id,
            packet.latitude,
            packet.longitude,
            packet.altitude
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
        
        # Add all rays to voxel grid
        self._last_rays = rays
        for ray in rays:
            self.voxel_grid.add_ray(
                ray.origin,
                ray.direction,
                ray.intensity
            )
        
        # ===== CALIBRATION FIX =====
        # Use CONFIRMED TRACKS for calibration, not raw hot voxels.
        # This prevents circular self-validation where a camera
        # calibrates against its own freshly-painted voxel.
        confirmed_tracks = self.tracker.get_confirmed_tracks()
        
        if confirmed_tracks and rays:
            # Use tracker-confirmed positions (filtered by multiple observations)
            track_positions = np.array([t.position for t in confirmed_tracks])
            
            for ray in rays:
                # Find the confirmed track that this ray points toward
                match_result = self._find_best_matching_voxel(
                    ray.origin, ray.direction, track_positions
                )
                
                if match_result is not None:
                    best_position, track_idx = match_result

                    self.calibrator.add_observation(
                        packet.camera_id,
                        ray.direction,
                        best_position,
                        ray.origin
                    )

                    # Estimate physical size and update track
                    if hasattr(ray, 'angular_size') and ray.angular_size > 0:
                        dist = np.linalg.norm(best_position - ray.origin)
                        # Physical Size = 2 * D * tan(theta / 2)
                        estimated_size = 2.0 * dist * np.tan(np.radians(ray.angular_size) / 2.0)

                        track = confirmed_tracks[track_idx]
                        self.tracker._track_manager.update_track(
                            track.track_id,
                            best_position,
                            0.0, # no time step for pure size update
                            physical_size=estimated_size
                        )
    
    def _find_best_matching_voxel(
        self,
        ray_origin: np.ndarray,
        ray_direction: np.ndarray,
        candidate_positions: np.ndarray
    ) -> Optional[Tuple[np.ndarray, int]]:
        """
        Find the position that best matches a ray's direction.
        
        Uses ray-point distance to find the closest position to the ray.
        Works for both hot voxels and confirmed track positions.

        Returns:
            Tuple of (closest_position, index) or None
        """
        if len(candidate_positions) == 0:
            return None
        
        # Calculate distance from each position to the ray
        # Distance = ||(P - O) - ((P - O) . D) * D|| where P=point, O=origin, D=direction
        to_points = candidate_positions - ray_origin
        projections = np.dot(to_points, ray_direction)
        
        # Only consider positions in front of the camera (positive projection)
        valid_mask = projections > 0
        if not np.any(valid_mask):
            return None
        
        # Calculate perpendicular distance to ray
        closest_on_ray = ray_origin + projections[:, np.newaxis] * ray_direction
        distances = np.linalg.norm(candidate_positions - closest_on_ray, axis=1)
        
        # Mask out positions behind camera
        distances[~valid_mask] = float('inf')
        
        # Return the closest position within a reasonable threshold (e.g., 10m)
        min_idx = np.argmin(distances)
        if distances[min_idx] < 10.0:
            return (candidate_positions[min_idx], min_idx)
        
        return None
    
    def _update_visualizer(self, detections: list = None) -> None:
        """Update the visualization."""
        if not self.visualizer:
            return
        
        # Use provided detections or fetch fresh
        if detections is None:
            detections = self.voxel_grid.get_detections()
        
        # Get camera positions
        cameras = [
            (cam_id, self.ray_builder.get_camera_position(cam_id))
            for cam_id in self.ray_builder.get_all_cameras()
        ]
        cameras = [(cid, pos) for cid, pos in cameras if pos is not None]
        
        # Get track positions
        tracks = [
            (track.track_id, track.position)
            for track in self.tracker.get_confirmed_tracks()
        ]
        
        # Get hot voxels
        hot_voxels = [
            (v.center, v.heat)
            for v in self.voxel_grid.get_hot_voxels()[:100]  # Limit for performance
        ]
        
        self.visualizer.update(
            detections=detections,
            camera_positions=cameras,
            tracks=tracks,
            hot_voxels=hot_voxels
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
            
            # Rate limiting
            elapsed = time.time() - frame_start
            sleep_time = frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        self.logger.info("system", "Server stopped")


def main():
    """Entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="OpticalRadar Server")
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
