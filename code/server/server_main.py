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
from typing import Optional, List, Tuple, Dict
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
    from .cluster_manager import ClusterManager, Cluster
    from .calibration import Calibrator
    from .visualizer import Visualizer
    from .websocket_server import WebSocketBroadcaster
    from .monitoring.node_health import NodeHealthMonitor
    from .monitoring.logger import StructuredLogger
    from .validation.ground_truth import GroundTruthValidator
    from .security.authenticator import Authenticator
except ImportError:
    from server.udp_server import UDPServer
    from server.cluster_manager import ClusterManager, Cluster
    from server.calibration import Calibrator
    from server.visualizer import Visualizer
    from server.websocket_server import WebSocketBroadcaster
    from server.monitoring.node_health import NodeHealthMonitor
    from server.monitoring.logger import StructuredLogger
    from server.validation.ground_truth import GroundTruthValidator
    from server.security.authenticator import Authenticator

class OpticalRadarServer:
    """Main orchestrator for the server backend."""
    
    def __init__(self, config_path: str = 'config.yaml', headless: bool = False):
        self.logger = StructuredLogger()
        self.logger.info("system", "Initializing OpticalRadar server")
        
        self.config = load_config(config_path)
        self.headless = headless
        self.running = False

        # Determine if security should be enabled
        sec_env = os.environ.get('OR_SECURITY_ENABLED', '').lower()
        sec_obj = getattr(self.config, 'security', None)
        sec_config = getattr(sec_obj, 'enabled', True) if sec_obj else True
        # Disable if environment explicitly says false, otherwise follow config
        security_enabled = False if sec_env in ('0', 'false') else sec_config

        # 1. Security Initialization
        self.authenticator = None
        if security_enabled:
            try:
                self.authenticator = Authenticator()
                self.logger.info("security", "Authentication system enabled")
            except Exception as e:
                self.logger.error("security", f"Failed to initialize authenticator: {e}")
                self.logger.error("security", "Security is enabled but authenticator failed. Halting.")
                raise RuntimeError("Authentication initialization failed")
        else:
            self.logger.warning("security", "Authentication system disabled via configuration")

        # 2. Network & Comms
        self.udp_server = UDPServer(self.config)

        server_config = getattr(self.config, 'server', None)
        ws_port = getattr(server_config, 'ws_port', 8080) if server_config else 8080
        self.ws_server = WebSocketBroadcaster(port=ws_port)

        # Register command handlers for multi-cluster support
        if hasattr(self.ws_server, 'register_command_handler'):
            self.ws_server.register_command_handler('CREATE_CLUSTER', self._handle_create_cluster)
            self.ws_server.register_command_handler('ASSIGN_NODE', self._handle_assign_node)

        # 3. Processing Core (Replaced Monolithic tracker with ClusterManager)
        self.cluster_manager = ClusterManager(self.config)
        self.calibrator = Calibrator(self.config)

        # Legacy mappings for system_test compatibility
        self._default_cluster = self.cluster_manager.clusters['DEFAULT']
        self.voxel_grid = self._default_cluster.voxel_grid
        self.tracker = self._default_cluster.tracker
        self.ray_builder = self._default_cluster.ray_builder

        # 4. Monitoring & Validation
        self.node_health = NodeHealthMonitor()
        self.health_monitor = self.node_health # Keep old reference just in case
        self.ground_truth = GroundTruthValidator()
        self.gt_evaluator = self.ground_truth
        
        # 5. Visualization
        self.visualizer = None
        if not self.headless:
            self.visualizer = Visualizer()

        self._setup_signal_handlers()
        
        # Performance tracking
        self._frame_count = 0
        self.frame_count = 0
        self.last_fps_time = time.time()
        self._start_time = time.time()
        self._last_frame_time = time.time()
        self._fps = 0.0
        self.current_fps = 0.0

    def _handle_create_cluster(self, client_id: str, payload: dict):
        """WebSocket handler for CREATE_CLUSTER command"""
        cluster_id = payload.get('cluster_id')
        if cluster_id:
            self.cluster_manager.create_cluster(cluster_id)
            self.logger.info("cluster", f"Created new cluster: {cluster_id}")
            self._broadcast_system_status()

    def _handle_assign_node(self, client_id: str, payload: dict):
        """WebSocket handler for ASSIGN_NODE command"""
        node_id = payload.get('node_id')
        cluster_id = payload.get('cluster_id')
        if node_id and cluster_id:
            success = self.cluster_manager.assign_node(node_id, cluster_id)
            if success:
                self.logger.info("cluster", f"Assigned node {node_id} to cluster {cluster_id}")
                self._broadcast_system_status()
            else:
                self.logger.warning("cluster", f"Failed to assign node {node_id} to cluster {cluster_id}")

    def _setup_signal_handlers(self):
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        self.logger.info("system", f"Received signal {signum}, initiating shutdown...")
        self.stop()

    def start(self):
        """Start all server components."""
        self.running = True
        self.udp_server.start()
        self.ws_server.start()
        
        self.logger.info("system", "OpticalRadar server started successfully")
        
        try:
            self._run_loop()
        except Exception as e:
            self.logger.error("system", f"Fatal error in main loop: {e}")
        finally:
            self.stop()

    def stop(self):
        """Stop all server components cleanly."""
        self.running = False
        self.udp_server.stop()
        self.ws_server.stop()
        if self.visualizer:
            self.visualizer.close()
        self.logger.info("system", "OpticalRadar server shutdown complete")

    def _process_ground_truth_packet(self, gt_packet, address):
        """Process an incoming ground truth packet."""
        self.logger.debug("network", f"Received Ground Truth from {address}")

        # We process ground truth across all clusters for now,
        # or we could associate it with a specific cluster if GT packets included a cluster_id.
        for cluster_id, cluster in self.cluster_manager.get_all_clusters().items():
            cam_pos = cluster.ray_builder.get_camera_position("GT_SOURCE") # Fake source
            if cam_pos is None:
               cam_pos = [0.0, 0.0, 0.0]

            # Generate fake rays representing the GT target to feed into the tracker
            # This allows the GT target to be tracked and evaluated.
            lat, lon, alt = gt_packet.latitude, gt_packet.longitude, gt_packet.altitude
            
            # Use ray_builder to create dummy rays just to inject the position
            rays = cluster.ray_builder.build_rays_from_packet(
               "GT_SOURCE",
               lat, lon, alt,
               (1.0, 0.0, 0.0, 0.0), # Identity orientation
               [] # No vectors
            )
            
            # Extract target ID from packet (assuming it's in the packet, otherwise use 0)
            target_id = getattr(gt_packet, 'target_id', 0)

            self.gt_evaluator.process_ground_truth(
                gt_packet
            )

    def _process_announce_packet(self, announce_packet, address):
        """Process a node announcement packet."""
        node_id = announce_packet.camera_id
        self.logger.info("network", f"Node announcement received from {node_id} at {address}")

        # Auto-assign to DEFAULT cluster for now if unassigned
        if not self.cluster_manager.get_cluster_for_node(node_id):
            self.cluster_manager.assign_node(node_id, 'DEFAULT')

    def _process_packet(self, packet, address):
        """Route a packet to the correct cluster based on camera_id."""

        # Security Check
        if self.authenticator and hasattr(packet, 'signature'):
            if not self.authenticator.verify_packet(packet):
                self.logger.warning("security", f"Signature verification failed for packet from {address}")
                return

        if packet.packet_type == PACKET_TYPE_GROUND_TRUTH:
             self._process_ground_truth_packet(packet, address)
             return

        if packet.packet_type == PACKET_TYPE_ANNOUNCE:
            self._process_announce_packet(packet, address)
            return

        if packet.packet_type != PACKET_TYPE_TELEMETRY:
            self.logger.warning("network", f"Unknown packet type {packet.packet_type} from {address}")
            return

        node_id = packet.camera_id
        
        # Update node health
        self.health_monitor.update(
            node_id=node_id,
            battery=packet.battery_level,
            temp=packet.temperature,
            status=packet.status_flags
        )

        # Route to specific cluster
        cluster = self.cluster_manager.get_cluster_for_node(node_id)
        if not cluster:
            # Node is unassigned (in pending pool), do not process telemetry for tracking
            return

        # 1. Build Rays
        rays = cluster.ray_builder.build_rays_from_packet(
            node_id,
            packet.latitude,
            packet.longitude,
            packet.altitude,
            packet.orientation,
            packet.vectors
        )
        
        # 2. Add to Voxel Grid
        cluster.voxel_grid.add_rays_batch(rays)
        
        # Provide rays for visualization if this cluster is active
        # In a real UI, we'd visualize the active cluster. For headless/legacy, we combine or pick default.
        if self.visualizer:
            self.visualizer.update_rays(rays)

        # 3. Broadcast Node Update (Global)
        cam_pos = cluster.ray_builder.get_camera_position(node_id)
        if cam_pos is None:
            cam_pos = [0.0, 0.0, 0.0]

        self.ws_server.broadcast_node_update({
            "id": node_id,
            "cluster_id": cluster.cluster_id,
            "location": cam_pos,
            "status": "active",
            "battery": packet.battery_level,
            "last_seen": time.time()
        })


    def _run_loop(self):
        """Main processing loop executed at a fixed frequency."""
        server_config = getattr(self.config, 'server', None)
        target_fps = getattr(server_config, 'target_fps', 30) if server_config else 30
        frame_time = 1.0 / target_fps
        
        while self.running:
            loop_start = time.time()
            
            # 1. Process all available network packets
            packets = self.udp_server.get_packets()
            for packet, address in packets:
                self._process_packet(packet, address)

            # 2. Tick all active clusters
            for cluster_id, cluster in self.cluster_manager.get_all_clusters().items():

                # Decay voxels
                cluster.voxel_grid.decay()

                # Extract detections (hot voxels)
                detections = cluster.voxel_grid.get_detections()

                # Update Tracker
                cluster.tracker.update(detections)
                tracks = cluster.tracker.get_active_tracks()

                # Update visualizer (just combining for local headless vis for now)
                if self.visualizer:
                    self.visualizer.update_detections(detections)
                    self.visualizer.update_tracks(tracks)

                # Evaluate against ground truth
                if len(self.gt_evaluator.get_metrics()) > 0:
                     if tracks:
                          best_track = tracks[0] # Simplification
                          self.gt_evaluator.evaluate(np.array(best_track.position))

                # Broadcast isolated tracks to clients subscribed to this cluster
                self._broadcast_tracks(cluster_id, tracks)
            
            # 3. Render Visualization (if enabled)
            if self.visualizer:
                self.visualizer.render()

            # 4. Broadcast System Status & Metrics
            self._calculate_fps(loop_start)
            if self.frame_count % target_fps == 0:  # ~Once per second
                self._broadcast_system_status()

            # 5. Sleep to maintain target FPS
            elapsed = time.time() - loop_start
            sleep_time = max(0, frame_time - elapsed)
            time.sleep(sleep_time)

            self.frame_count += 1

    def process_frame(self):
        """Legacy helper for testing."""
        # Tick all active clusters
        for cluster_id, cluster in self.cluster_manager.get_all_clusters().items():
            cluster.voxel_grid.decay()
            detections = cluster.voxel_grid.get_detections()
            cluster.tracker.update(detections)
        self._frame_count += 1

    def _broadcast_tracks(self, cluster_id: str, tracks: List['Track']):
        """Broadcast track data to UI clients subscribed to the specific cluster."""
        track_data = []
        for track in tracks:
            track_data.append({
                "id": f"T-{track.id}",
                "position": track.position,
                "velocity": track.velocity,
                "confidence": getattr(track, 'confidence', 1.0),
                "physical_size": getattr(track, 'physical_size', 0.0)
            })

        # Target specific cluster room
        if hasattr(self.ws_server, 'broadcast_tracks'):
            import inspect
            sig = inspect.signature(self.ws_server.broadcast_tracks)
            if 'room' in sig.parameters:
                self.ws_server.broadcast_tracks(track_data, room=cluster_id)
            else:
                self.ws_server.broadcast_tracks(track_data)

    def _broadcast_system_status(self):
        """Broadcast overall system health and cluster topology."""

        # Serialize cluster topology
        clusters_info = {}
        for c_id, cluster in self.cluster_manager.get_all_clusters().items():
            clusters_info[c_id] = {
                "id": c_id,
                "nodes": list(cluster.assigned_nodes),
                "effective_volume": self.cluster_manager.calculate_effective_volume(c_id)
            }

        status_data = {
            "fps": round(self.current_fps, 1),
            "cpu_usage": 0.0, # Placeholder
            "memory_usage": 0.0, # Placeholder
            "uptime": int(time.time() - self.last_fps_time), # Roughly
            "clusters": clusters_info,
            "pending_nodes": list(self.cluster_manager.pending_nodes)
        }
        self.ws_server.broadcast_system_status(status_data)

    def _calculate_fps(self, loop_start: float):
        """Calculate processing frames per second."""
        if self.frame_count % 30 == 0:
            now = time.time()
            self.current_fps = 30.0 / (now - self.last_fps_time)
            self.last_fps_time = now

if __name__ == "__main__":
    server = OpticalRadarServer()
    server.start()
