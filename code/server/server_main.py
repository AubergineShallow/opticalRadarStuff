
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
import json
from typing import Optional, List, Tuple, Dict
import numpy as np

# Add parent to path for absolute imports
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from common.config import load as load_config, Config
from common.protocol import TelemetryPacket, PACKET_TYPE_TELEMETRY, PACKET_TYPE_GROUND_TRUTH, PACKET_TYPE_ANNOUNCE, AnnouncePacket
from common.node_specs import load_all_specs, default_spec, NodeSpec
from math_utils.geo import wgs84_to_enu

# Use try/except for both module and direct execution support
try:
    from .udp_server import UDPServer
    from .cluster_manager import ClusterManager, Cluster
    from .calibration import Calibrator
    from .validation.calibration_validator import CalibrationValidator
    from .visualizer import Visualizer
    from .websocket_server import WebSocketBroadcaster
    from .foxglove_broadcaster import FoxgloveBroadcaster
    from .monitoring.node_health import NodeHealthMonitor
    from .monitoring.logger import StructuredLogger
    from .monitoring.metrics import (
        get_metrics, METRIC_ACTIVE_TRACKS, METRIC_PACKETS_PROCESSED,
        METRIC_PROCESSING_TIME, METRIC_CALIBRATION_SCORE,
    )
    from .validation.ground_truth import GroundTruthValidator
    from .security.authenticator import Authenticator
    from .security.key_manager import KeyManager
    from .tracking.tracker import Detection
except ImportError:
    from server.udp_server import UDPServer
    from server.cluster_manager import ClusterManager, Cluster
    from server.calibration import Calibrator
    from server.validation.calibration_validator import CalibrationValidator
    from server.visualizer import Visualizer
    from server.websocket_server import WebSocketBroadcaster
    from server.foxglove_broadcaster import FoxgloveBroadcaster
    from server.monitoring.node_health import NodeHealthMonitor
    from server.monitoring.logger import StructuredLogger
    from server.monitoring.metrics import (
        get_metrics, METRIC_ACTIVE_TRACKS, METRIC_PACKETS_PROCESSED,
        METRIC_PROCESSING_TIME, METRIC_CALIBRATION_SCORE,
    )
    from server.validation.ground_truth import GroundTruthValidator
    from server.security.authenticator import Authenticator
    from server.security.key_manager import KeyManager
    from server.tracking.tracker import Detection

try:
    from .uncertainty import measurement_covariance
except ImportError:
    from server.uncertainty import measurement_covariance

def _to_list(value):
    """Convert numpy arrays / tuples to JSON-serialisable plain lists."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return [float(v) for v in value]
    return value


class OpticalRadarServer:
    """Main orchestrator for the server backend."""
    
    def __init__(self, config_path: str = 'config.yaml', headless: bool = False):
        self.logger = StructuredLogger()
        self.logger.info("system", "Initializing OpticalRadar server")
        
        self.config = load_config(config_path)
        self.headless = headless
        self.running = False

        # Determine if security should be enabled. The env var can force it
        # either way; otherwise follow config (which defaults to off so the
        # system works out of the box with unsigned edge nodes).
        sec_env = os.environ.get('OR_SECURITY_ENABLED', '').strip().lower()
        sec_obj = getattr(self.config, 'security', None)
        sec_config = getattr(sec_obj, 'enabled', False) if sec_obj else False
        if sec_env in ('0', 'false', 'no', 'off'):
            security_enabled = False
        elif sec_env in ('1', 'true', 'yes', 'on'):
            security_enabled = True
        else:
            security_enabled = sec_config

        # 1. Security Initialization (P5.1: one KeyManager owns the keys; the
        #    Authenticator is a thin consumer that looks them up per node.)
        self.authenticator = None
        self.key_manager = None
        if security_enabled:
            try:
                key_file = getattr(sec_obj, 'key_file', None) if sec_obj else None
                self.key_manager = KeyManager(key_file=key_file)
                self.authenticator = Authenticator(key_manager=self.key_manager)
                self.logger.info("security", "Authentication system enabled")
            except Exception as e:
                self.logger.error("security", f"Failed to initialize authenticator: {e}")
                self.logger.error("security", "Security is enabled but authenticator failed. Halting.")
                raise RuntimeError("Authentication initialization failed")
        else:
            self.logger.warning("security", "Authentication system disabled via configuration")

        # 2. Network & Comms
        # UDPServer's first positional arg is the port int, NOT a Config object;
        # passing self.config bound a Config to self.port and crashed on bind
        # (BUG-007). Map the network config explicitly. Authentication stays an
        # object-level check in _process_packet (single per-node KeyManager path).
        net_cfg = getattr(self.config, 'network', None)
        self.udp_server = UDPServer(
            port=getattr(net_cfg, 'udp_port', 5005) if net_cfg else 5005,
            max_packet_size=getattr(net_cfg, 'max_packet_size', 65535) if net_cfg else 65535,
        )

        # WS port defaults to 5000 to match the frontend Env.WS_URL (the old 8080
        # fallback meant the UI could never connect out of the box — BUG-010).
        server_config = getattr(self.config, 'server', None)
        ws_port = getattr(server_config, 'ws_port', 5000) if server_config else 5000
        self.ws_server = WebSocketBroadcaster(port=ws_port)

        # Optional parallel Foxglove/Flora broadcaster (add-on). Read its config
        # the same defensive way every other subsystem does; it stays fully inert
        # unless foxglove.enabled is set AND foxglove-sdk is importable.
        fg_cfg = getattr(self.config, 'foxglove', None)
        self.fg_server = FoxgloveBroadcaster(
            port=getattr(fg_cfg, 'port', 8765) if fg_cfg else 8765,
            enabled=getattr(fg_cfg, 'enabled', False) if fg_cfg else False,
        )

        # Register command handlers for multi-cluster support
        if hasattr(self.ws_server, 'register_command_handler'):
            self.ws_server.register_command_handler('CREATE_CLUSTER', self._handle_create_cluster)
            self.ws_server.register_command_handler('ASSIGN_NODE', self._handle_assign_node)

        # 3. Processing Core (Replaced Monolithic tracker with ClusterManager)
        self.cluster_manager = ClusterManager(self.config)

        # Per-node optics registry: the source of angular (bearing) uncertainty.
        # Seeded from config/node_specs.json so a sigma_theta is available even
        # before a node announces, then updated live from each AnnouncePacket's
        # FOV/resolution. Feeds per-detection measurement covariance (P-optics).
        self._node_optics: Dict[str, NodeSpec] = load_all_specs()
        self._default_optics: NodeSpec = default_spec()
        # measurement_covariance() tuning: large along-ray (depth) sigma since a
        # single bearing barely constrains range; cross-range floor tied to the
        # voxel resolution (quantisation scale).
        grid_cfg = getattr(self.config, 'grid', None)
        self._uncert_sigma_range = 100.0
        self._uncert_min_cross_range = getattr(grid_cfg, 'resolution_m', 1.0) if grid_cfg else 1.0

        # Calibration feedback loop (P1.5). Calibrator takes solver parameters
        # (not a Config object) plus a validator that gates corrections.
        cal_cfg = getattr(self.config, 'calibration', None)
        self._calibration_enabled = getattr(cal_cfg, 'enabled', True) if cal_cfg else True
        self._calibration_min_hits = getattr(cal_cfg, 'min_track_hits', 3) if cal_cfg else 3
        self._calibration_assoc_radius = getattr(cal_cfg, 'association_radius_m', 10.0) if cal_cfg else 10.0
        self._calibration_offsets_path = getattr(cal_cfg, 'offsets_file', 'secrets/calibration_offsets.json') if cal_cfg else 'secrets/calibration_offsets.json'

        validator = CalibrationValidator(
            max_correction_degrees=getattr(cal_cfg, 'max_correction_degrees', 15.0) if cal_cfg else 15.0,
            min_observations=getattr(cal_cfg, 'min_observations', 100) if cal_cfg else 100,
        )
        self.calibrator = Calibrator(
            buffer_size=getattr(cal_cfg, 'buffer_size', 2000) if cal_cfg else 2000,
            solve_interval=getattr(cal_cfg, 'solve_interval', 10.0) if cal_cfg else 10.0,
            blend_factor=getattr(cal_cfg, 'blend_factor', 0.1) if cal_cfg else 0.1,
            validator=validator,
        )

        # Per-node calibration status: uncalibrated / converging / converged / diverged
        self._calibration_status: Dict[str, str] = {}
        # Offsets persisted across restarts; applied to a node's ray_builder on
        # its first packet so calibration survives a restart.
        self._persisted_offsets: Dict[str, tuple] = {}
        self._load_calibration_offsets()
        self._last_calibration = time.time()

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
        self.metrics = get_metrics()  # P5.2: shared metrics collector
        
        # 5. Visualization
        self.visualizer = None
        if not self.headless:
            self.visualizer = Visualizer()

        self._setup_signal_handlers()
        
        # Performance tracking
        self.frame_count = 0
        self.last_fps_time = time.time()
        # BUG-006: uptime must be derived from a monotonic clock so an NTP step
        # or manual clock adjustment can't make it jump or go negative.
        self._start_time = time.monotonic()
        self._last_frame_time = time.time()
        self.current_fps = 0.0

        # P2.1: throttle for structural octree housekeeping (consolidate_and_prune)
        self._last_consolidate = time.time()

        # Rays built this frame, keyed by cluster_id, flushed to the UI during the
        # per-cluster tick so the ray layer isn't permanently empty in live mode.
        self._pending_rays: Dict[str, list] = {}

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
        self.fg_server.start()

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
        self.fg_server.stop()
        if self.visualizer:
            self.visualizer.close()
        self.logger.info("system", "OpticalRadar server shutdown complete")

    def _process_ground_truth_packet(self, gt_packet, address):
        """Record an incoming ground-truth target for accuracy evaluation."""
        self.logger.debug("network", f"Received Ground Truth from {address}")

        # Convert the GT packet's geodetic position into the ENU frame the
        # tracker and GroundTruthValidator operate in, using a ray_builder's
        # configured reference origin (all clusters share the same origin).
        rb = self._default_cluster.ray_builder
        e, n, u = wgs84_to_enu(
            gt_packet.latitude, gt_packet.longitude, gt_packet.altitude,
            rb.ref_lat, rb.ref_lon, rb.ref_alt
        )
        target_id = getattr(gt_packet, 'target_id', 0)
        timestamp = getattr(gt_packet, 'timestamp', time.time())

        # add_ground_truth is the real GroundTruthValidator API. The old
        # process_ground_truth() call did not exist and raised AttributeError
        # on every ground-truth packet.
        self.gt_evaluator.add_ground_truth(
            object_id=str(target_id),
            position=np.array([e, n, u]),
            timestamp=timestamp,
        )

    def _process_announce_packet(self, announce_packet, address):
        """Process a node announcement packet."""
        node_id = announce_packet.camera_id
        self.logger.info("network", f"Node announcement received from {node_id} at {address}")

        # Record the node's advertised optics so its bearing uncertainty reflects
        # the real hardware rather than a nominal default. This is the previously
        # discarded half of the announce handshake (the packet always carried FOV
        # + resolution; nothing consumed it).
        try:
            self._node_optics[node_id] = NodeSpec(
                node_id=node_id,
                sensor=self._node_optics.get(node_id, self._default_optics).sensor,
                fov_horizontal=float(announce_packet.fov_horizontal),
                fov_vertical=float(announce_packet.fov_vertical),
                resolution_width=int(announce_packet.resolution_width),
                resolution_height=int(announce_packet.resolution_height),
            )
        except (AttributeError, TypeError, ValueError) as e:
            self.logger.warning("network", f"Announce from {node_id} had unusable optics: {e}")

        # Auto-assign to DEFAULT cluster for now if unassigned
        if not self.cluster_manager.get_cluster_for_node(node_id):
            self.cluster_manager.assign_node(node_id, 'DEFAULT')

    def _node_sigma_theta(self, node_id: str) -> float:
        """Bearing uncertainty (radians) for a node, from its live/announced or
        file-provisioned optics, falling back to the default spec."""
        return self._node_optics.get(node_id, self._default_optics).sigma_theta_rad

    def _build_detections(self, cluster, centroids) -> List['Detection']:
        """Wrap voxel-cluster centroids as Detection objects, attaching a 3x3
        positional measurement covariance derived from the optics of the nodes
        assigned to this cluster (see server.uncertainty). Falls back to no
        covariance (tracker uses its default isotropic R) when no node position
        is known yet."""
        rb = cluster.ray_builder
        cams = []
        for cam_id in rb.get_all_cameras():
            pos = rb.get_camera_position(cam_id)
            if pos is not None:
                cams.append((pos, self._node_sigma_theta(cam_id)))

        det_objs = []
        for c in centroids:
            pos = np.asarray(c)
            R = measurement_covariance(
                pos, cams,
                sigma_range=self._uncert_sigma_range,
                min_cross_range=self._uncert_min_cross_range,
            ) if cams else None
            det_objs.append(Detection(position=pos, covariance=R))
        return det_objs

    def _process_packet(self, packet, address):
        """Route a packet to the correct cluster based on camera_id."""

        # Security Check (P5.1: object-level verify with per-node key lookup)
        if self.authenticator and hasattr(packet, 'signature'):
            if not self.authenticator.verify_telemetry_packet(packet):
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
        self.health_monitor.record_packet(
            node_id=node_id,
            packet_timestamp=packet.timestamp,
            sequence=packet.sequence_number,
            health_flags=packet.health_flags
        )

        # Route to specific cluster
        cluster = self.cluster_manager.get_cluster_for_node(node_id)
        if not cluster:
            # Node is unassigned (in pending pool), do not process telemetry for tracking
            return

        # Apply any persisted calibration offset before building this node's rays.
        self._ensure_calibration_offset(cluster, node_id)

        # 1. Build Rays
        rays = cluster.ray_builder.build_rays_from_packet(
            node_id,
            packet.latitude,
            packet.longitude,
            packet.altitude,
            packet.orientation,
            packet.vectors
        )

        # 2. Add to Voxel Grid (frame_index drives the co-temporal camera window
        #    used for multi-camera subdivision — P2.5).
        cluster.voxel_grid.add_rays_batch(rays, frame_index=self.frame_count)

        # Buffer this node's rays for the per-frame RAY_UPDATE broadcast.
        if rays:
            self._pending_rays.setdefault(cluster.cluster_id, []).extend(rays)

        # Feed the calibration solver with observations against confirmed tracks (P1.5).
        self._collect_calibration_observations(cluster, node_id, rays)

        # Metrics (P5.2)
        self.metrics.increment_counter(METRIC_PACKETS_PROCESSED)
        
        # Provide rays for visualization if this cluster is active
        # In a real UI, we'd visualize the active cluster. For headless/legacy, we combine or pick default.
        if self.visualizer:
            self.visualizer.update_rays(rays)

        # 3. Broadcast Node Update (Global)
        cam_pos = cluster.ray_builder.get_camera_position(node_id)
        if cam_pos is None:
            cam_pos = [0.0, 0.0, 0.0]

        # Status as the numeric NodeHealthStatus the frontend expects (0=HEALTHY,
        # 1=DEGRADED). The old "active" string never equalled the enum, so every
        # live node rendered red. Derive from the health_flags (GPS|CAM|IMU bits).
        node_status = 0 if (packet.health_flags & 0x07) == 0x07 else 1

        node_update = {
            "id": node_id,
            "node_id": node_id,
            "cluster_id": cluster.cluster_id,
            "location": _to_list(cam_pos),
            "status": node_status,
            # TelemetryPacket has no battery field (OQ5). health_flags is the
            # closest proxy the protocol carries; battery is omitted until a
            # protocol v4 extension adds it.
            "battery": None,
            "health_flags": packet.health_flags,
            "last_seen": time.time()
        }
        self.ws_server.broadcast_node_update(node_update)

        # Mirror to the Foxglove add-on: the same node dict, plus the raw GPS fix
        # for Flora's Map panel (raw lat/lon/alt is already in scope here, so no
        # ENU reverse-conversion is needed).
        self.fg_server.publish_node_update(node_update)
        self.fg_server.publish_node_location(
            node_id, packet.latitude, packet.longitude, packet.altitude
        )


    def _run_loop(self):
        """Main processing loop executed at a fixed frequency."""
        server_config = getattr(self.config, 'server', None)
        target_fps = getattr(server_config, 'target_fps', 30) if server_config else 30
        frame_time = 1.0 / target_fps
        
        while self.running:
            loop_start = time.time()
            
            # 1. Process all available network packets
            packets = self.udp_server.get_packets()
            for received in packets:
                self._process_packet(received.packet, (received.sender_ip, received.sender_port))

            # P2.1: per-frame heat decay (30Hz) is decoupled from structural
            # consolidation (throttled), so heat fades at the configured rate
            # instead of accumulating between housekeeping ticks.
            now = time.time()
            do_consolidate = (now - self._last_consolidate) >= 1.5

            # 2. Tick all active clusters
            for cluster_id, cluster in self.cluster_manager.get_all_clusters().items():

                # Per-frame heat decay (cheap, zero allocation).
                cluster.voxel_grid.decay_active_leaves()

                # Throttled structural housekeeping (collapse cooled leaves).
                if do_consolidate:
                    cluster.voxel_grid.consolidate_and_prune()

                # Extract detections (hot voxels) and wrap as Detection objects
                # for the tracker (get_detections yields centroid np.ndarrays).
                # Each detection carries a measurement covariance built from the
                # optics/geometry of the nodes that triangulated it (P-optics).
                detections = cluster.voxel_grid.get_detections()
                det_objs = self._build_detections(cluster, detections)

                # Update Tracker
                cluster.tracker.update(det_objs)
                tracks = cluster.tracker.get_all_tracks()

                # Update visualizer (just combining for local headless vis for now)
                if self.visualizer:
                    self.visualizer.update_detections(detections)
                    self.visualizer.update_tracks(tracks)

                # Evaluate the best track against ground truth. compare_detection
                # is the real GroundTruthValidator API (the old get_metrics()/
                # evaluate() calls did not exist and crashed the loop on frame 1).
                # It is a no-op — returns (None, inf) — when no GT is registered,
                # so it is safe to call every frame.
                if tracks:
                    best_track = tracks[0]  # Simplification
                    self.gt_evaluator.compare_detection(
                        np.asarray(best_track.position), time.time()
                    )

                # Broadcast isolated tracks to clients subscribed to this cluster
                self._broadcast_tracks(cluster_id, tracks)

                # Broadcast the hot-voxel heatmap and this frame's sensor rays so
                # the UI voxel/ray layers are populated in live mode (not just mock).
                self._broadcast_voxels(cluster_id, cluster.voxel_grid)
                cluster_rays = self._pending_rays.pop(cluster_id, [])
                self._broadcast_rays(cluster_id, cluster_rays)

                # Mirror this cluster's tracks/voxels/rays into a Foxglove
                # SceneUpdate for Flora's 3D panel (add-on; no-op when disabled).
                self.fg_server.publish_scene(
                    cluster_id, tracks,
                    cluster.voxel_grid.get_hot_voxels(), cluster_rays,
                )

                # Metrics: active track count per cluster (P5.2)
                self.metrics.set_gauge(METRIC_ACTIVE_TRACKS, len(tracks),
                                       labels={"cluster": cluster_id})

            # Drop rays for any cluster that didn't tick this frame (e.g. pending
            # nodes) so the buffer can't grow unbounded.
            self._pending_rays.clear()

            if do_consolidate:
                self._last_consolidate = now

            # Metrics: per-frame processing time (P5.2)
            self.metrics.observe_histogram(METRIC_PROCESSING_TIME, time.time() - loop_start)

            # Periodic calibration solve (P1.5): gated by solve_interval.
            if now - self._last_calibration >= self.calibrator.solve_interval:
                self._run_calibration()
                self._last_calibration = now

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
            cluster.voxel_grid.decay_active_leaves()
            detections = cluster.voxel_grid.get_detections()
            # get_detections() yields centroid positions (np.ndarray); the tracker
            # consumes Detection objects with a .position attribute. Attach the
            # optics-derived measurement covariance (P-optics).
            det_objs = self._build_detections(cluster, detections)
            cluster.tracker.update(det_objs)
        self.frame_count += 1

    # ------------------------------------------------------------------ #
    # Calibration feedback loop (P1.5)                                   #
    # ------------------------------------------------------------------ #
    def _cluster_for_node(self, node_id: str):
        """Return the cluster a node is assigned to, or None (no side effects)."""
        cluster_id = self.cluster_manager.node_assignments.get(node_id)
        if cluster_id:
            return self.cluster_manager.clusters.get(cluster_id)
        return None

    def _load_calibration_offsets(self):
        """Load persisted calibration offsets from disk (applied per-node later)."""
        path = self._calibration_offsets_path
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                for node_id, quat in data.items():
                    offset = tuple(float(x) for x in quat)
                    self._persisted_offsets[node_id] = offset
                    # Seed the calibrator so its blending starts from saved state.
                    self.calibrator._offsets[node_id] = offset
                self.logger.info("calibration",
                                 f"Loaded {len(self._persisted_offsets)} calibration offset(s)")
        except Exception as e:
            self.logger.warning("calibration", f"Failed to load calibration offsets: {e}")

    def _save_calibration_offsets(self):
        """Persist current calibration offsets to disk."""
        path = self._calibration_offsets_path
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            data = {cam: list(off) for cam, off in self.calibrator._offsets.items()}
            with open(path, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            self.logger.warning("calibration", f"Failed to save calibration offsets: {e}")

    def _ensure_calibration_offset(self, cluster, node_id: str):
        """Apply a persisted offset to a node's ray_builder on first sight."""
        offset = self._persisted_offsets.get(node_id)
        if offset is not None and cluster.ray_builder.get_calibration_offset(node_id) is None:
            cluster.ray_builder.set_calibration_offset(node_id, offset)
            self._calibration_status.setdefault(node_id, "converged")

    def _collect_calibration_observations(self, cluster, node_id: str, rays):
        """
        Feed the solver observations from this node's rays, associated to nearby
        confirmed tracks. Tentative/low-confidence tracks are excluded — calibrating
        against noise would corrupt the solver.
        """
        if not self._calibration_enabled or not rays:
            return

        confirmed = [
            t for t in cluster.tracker.get_confirmed_tracks()
            if getattr(t, 'hit_count', 0) >= self._calibration_min_hits
        ]
        if not confirmed:
            return

        targets = [np.asarray(t.position, dtype=float) for t in confirmed]
        radius = self._calibration_assoc_radius

        for ray in rays:
            origin = np.asarray(ray.origin, dtype=float)
            direction = np.asarray(ray.direction, dtype=float)

            best_target = None
            best_dist = float('inf')
            for tp in targets:
                v = tp - origin
                t = max(0.0, float(np.dot(v, direction)))
                closest = origin + t * direction
                dist = float(np.linalg.norm(tp - closest))
                if dist < best_dist:
                    best_dist = dist
                    best_target = tp

            if best_target is not None and best_dist <= radius:
                self.calibrator.add_observation(node_id, direction, best_target, origin)
                self._calibration_status.setdefault(node_id, "converging")

    def _run_calibration(self):
        """Solve due cameras and push validator-accepted offsets into RayBuilders."""
        if not self._calibration_enabled:
            return

        results = self.calibrator.process()
        applied = False
        for result in results:
            node_id = result.camera_id
            # Metrics: calibration residual quality per node (P5.2)
            validator = getattr(self.calibrator, 'validator', None)
            if validator is not None:
                try:
                    self.metrics.set_gauge(METRIC_CALIBRATION_SCORE,
                                           validator.calculate_score(node_id),
                                           labels={"node": node_id})
                except Exception:
                    pass
            if result.approved:
                offset = self.calibrator.get_offset(node_id)
                cluster = self._cluster_for_node(node_id)
                if cluster:
                    cluster.ray_builder.set_calibration_offset(node_id, offset)
                    self._persisted_offsets[node_id] = tuple(offset)
                    self._calibration_status[node_id] = "converged"
                    applied = True
                    self.logger.info(
                        "calibration",
                        f"Applied {result.correction_degrees:.2f}° correction to {node_id}")
            else:
                # Mark diverged only when the validator flagged divergence.
                if "diverg" in (result.reason or "").lower():
                    self._calibration_status[node_id] = "diverged"

        if applied:
            self._save_calibration_offsets()

    def _broadcast_tracks(self, cluster_id: str, tracks: List['Track']):
        """Broadcast track data to UI clients subscribed to the specific cluster."""
        track_data = []
        for track in tracks:
            track_id = getattr(track, 'track_id', getattr(track, 'id', None))
            track_data.append({
                "id": f"T-{track_id}",
                "track_id": track_id,
                # State lets the UI distinguish tentative/confirmed/lost tracks.
                "state": int(getattr(track, 'state', 1)),
                # cluster_id is stamped on every wire object (not just used as the
                # delivery-room key) so a future "show all domains" view can
                # colour-code by cluster without a wire-format change (P0.6 note).
                "cluster_id": cluster_id,
                "position": _to_list(track.position),
                "velocity": _to_list(track.velocity),
                "confidence": getattr(track, 'confidence', 1.0),
                "physical_size": getattr(track, 'physical_size', 0.0)
            })

        # Deliver only to clients subscribed to this cluster's room. The full
        # current track list is sent every frame, so the UI can full-replace and
        # drop tracks that have disappeared (no per-track DELETED event is sent).
        self.ws_server.broadcast_tracks(track_data, room=cluster_id)

    def _broadcast_voxels(self, cluster_id: str, voxel_grid) -> None:
        """Broadcast the cluster's hot voxels to its room (UI heatmap layer)."""
        hot = voxel_grid.get_hot_voxels()
        voxel_data = [{
            "x": float(v.center[0]),
            "y": float(v.center[1]),
            "z": float(v.center[2]),
            "intensity": min(255.0, float(v.heat)),
            "cluster_id": cluster_id,
        } for v in hot[:256]]
        if hasattr(self.ws_server, 'broadcast_voxels'):
            self.ws_server.broadcast_voxels(voxel_data, room=cluster_id)

    def _broadcast_rays(self, cluster_id: str, rays) -> None:
        """Broadcast this frame's sensor rays to the cluster's room (UI ray layer)."""
        ray_data = [{
            "origin": _to_list(r.origin),
            "direction": _to_list(r.direction),
            "intensity": float(getattr(r, 'intensity', 0.0)),
            "camera_id": getattr(r, 'camera_id', ''),
            "cluster_id": cluster_id,
        } for r in rays[:256]]
        if hasattr(self.ws_server, 'broadcast_rays'):
            self.ws_server.broadcast_rays(ray_data, room=cluster_id)

    def _broadcast_system_status(self):
        """Broadcast overall system health and cluster topology."""

        # Serialize cluster topology
        clusters_info = {}
        # CLUSTER_UPDATE payload shaped to the frontend ClusterInfo type
        # (cluster_id, node_ids, track_count, voxel_resolution_m).
        clusters_wire = {}
        total_tracks = 0
        total_voxels = 0
        for c_id, cluster in self.cluster_manager.get_all_clusters().items():
            node_ids = list(cluster.assigned_nodes)
            clusters_info[c_id] = {
                "id": c_id,
                "nodes": node_ids,
                "effective_volume": self.cluster_manager.calculate_effective_volume(c_id)
            }
            track_count = len(cluster.tracker.get_confirmed_tracks())
            total_tracks += track_count
            total_voxels += cluster.voxel_grid.get_stats().get('active_leaves', 0)
            clusters_wire[c_id] = {
                "cluster_id": c_id,
                "node_ids": node_ids,
                "track_count": track_count,
                "voxel_resolution_m": cluster.voxel_grid.config.resolution_m,
            }

        # Keys MUST match the frontend SystemStatus type; the old fps/cpu_usage/
        # memory_usage/uptime keys diverged so the UI dashboard read undefined
        # and showed zeros for everything (BUG-011).
        status_data = {
            "server_fps": round(self.current_fps, 1),
            "cpu_percent": 0.0,     # Placeholder (no psutil dependency)
            "memory_percent": 0.0,  # Placeholder
            "total_tracks": total_tracks,
            "total_voxels": total_voxels,
            # Monotonic source (BUG-006): immune to wall-clock/NTP adjustments.
            "uptime_seconds": int(time.monotonic() - self._start_time),
            "clusters": clusters_info,
            "pending_nodes": list(self.cluster_manager.pending_nodes),
            # Per-node calibration status (P1.5): uncalibrated/converging/converged/diverged
            "calibration": dict(self._calibration_status),
            # Metrics snapshot folded into status (P5.2) — defers a real exporter.
            "metrics": self.metrics.snapshot(),
        }
        self.ws_server.broadcast_system_status(status_data)
        self.fg_server.publish_system_status(status_data)

        # Drive the frontend domain dropdown + pending-node list (P3.5).
        clusters_update = {
            "clusters": clusters_wire,
            "pending_nodes": list(self.cluster_manager.pending_nodes),
        }
        if hasattr(self.ws_server, 'broadcast_clusters'):
            self.ws_server.broadcast_clusters(clusters_update)
        self.fg_server.publish_clusters(clusters_update)

    def _calculate_fps(self, loop_start: float):
        """Calculate processing frames per second."""
        if self.frame_count % 30 == 0:
            now = time.time()
            self.current_fps = 30.0 / (now - self.last_fps_time)
            self.last_fps_time = now

def main(argv: Optional[List[str]] = None) -> int:
    """Entry point used by run_server.py and `python -m server.server_main`.

    Constructs the server and runs it. Returns a process exit code.
    """
    import argparse

    parser = argparse.ArgumentParser(description="OpticalRadar server")
    parser.add_argument(
        "--config", default="config.yaml",
        help="Path to config.yaml (built-in defaults are used if it is absent)")
    parser.add_argument(
        "--headless", action="store_true",
        help="Run without the local visualizer window")
    args = parser.parse_args(argv)

    server = OpticalRadarServer(config_path=args.config, headless=args.headless)
    server.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
