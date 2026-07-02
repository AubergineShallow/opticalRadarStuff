

#!/usr/bin/env python
"""
system_test.py - Full system orchestration test.

Verifies that all modules import correctly and the server + simulation
pipeline runs end-to-end without errors.
"""

import sys
import os
import time
import threading
import traceback

# Setup path
code_dir = os.path.dirname(os.path.abspath(__file__))
if code_dir not in sys.path:
    sys.path.insert(0, code_dir)

PASS = 0
FAIL = 0

def check(name, fn):
    """Run a check and report pass/fail."""
    global PASS, FAIL
    try:
        result = fn()
        if result is not None and not result:
            raise AssertionError(f"Returned {result}")
        PASS += 1
        print(f"  [PASS] {name}")
    except Exception as e:
        FAIL += 1
        print(f"  [FAIL] {name}: {e}")
        traceback.print_exc()



def test_geo():
    print("\n=== Phase X: Geo Math ===")
    from math_utils.geo import haversine_distance

    def test_haversine():
        # New York
        lat1, lon1 = 40.7128, -74.0060
        # London
        lat2, lon2 = 51.5074, -0.1278

        dist = haversine_distance(lat1, lon1, lat2, lon2)
        assert 5500000 < dist < 5600000, f"Distance NY to London expected ~5570km, got {dist/1000}km"

        # Identical points
        dist_zero = haversine_distance(lat1, lon1, lat1, lon1)
        assert dist_zero == 0.0, f"Distance to self expected 0.0, got {dist_zero}"

        # Antipodal points
        dist_antipodal = haversine_distance(0.0, 0.0, 0.0, 180.0)
        # pi * R = 3.14159 * 6371000 = 20015086.7
        assert 20000000 < dist_antipodal < 20030000, f"Distance antipodal expected ~20015km, got {dist_antipodal/1000}km"

        return True

    check("haversine_distance calculations", test_haversine)



def test_quaternion():
    print("\n=== Phase X: Quaternion Math ===")
    from math_utils.quaternion import normalize

    def test_normalize():
        # Standard normalization
        q = (1.0, 1.0, 1.0, 1.0)
        norm_q = normalize(q)
        assert abs(norm_q[0] - 0.5) < 1e-6, f"Expected 0.5 for w, got {norm_q[0]}"
        assert abs(norm_q[1] - 0.5) < 1e-6, f"Expected 0.5 for x, got {norm_q[1]}"
        assert abs(norm_q[2] - 0.5) < 1e-6, f"Expected 0.5 for y, got {norm_q[2]}"
        assert abs(norm_q[3] - 0.5) < 1e-6, f"Expected 0.5 for z, got {norm_q[3]}"

        # Zero magnitude edge case
        zero_q = (0.0, 0.0, 0.0, 0.0)
        norm_zero = normalize(zero_q)
        assert norm_zero == (1.0, 0.0, 0.0, 0.0), f"Expected identity for zero mag, got {norm_zero}"

        return True

    check("quaternion normalize calculations", test_normalize)


def test_imports():
    """Test that all modules import without errors."""
    print("\n=== Phase 1: Import Verification ===")
    
    check("common.constants", lambda: __import__("common.constants"))
    check("common.config", lambda: __import__("common.config"))
    check("common.protocol", lambda: __import__("common.protocol"))
    check("math_utils.geo", lambda: __import__("math_utils.geo"))
    check("math_utils.quaternion", lambda: __import__("math_utils.quaternion"))
    check("server.udp_server", lambda: __import__("server.udp_server"))
    check("server.ray_builder", lambda: __import__("server.ray_builder"))
    check("server.voxel_grid", lambda: __import__("server.voxel_grid"))
    check("server.calibration", lambda: __import__("server.calibration"))
    check("server.websocket_server", lambda: __import__("server.websocket_server"))
    check("server.foxglove_broadcaster", lambda: __import__("server.foxglove_broadcaster"))
    check("server.tracking.tracker", lambda: __import__("server.tracking.tracker"))
    check("server.tracking.kalman_filter", lambda: __import__("server.tracking.kalman_filter"))
    check("server.tracking.data_association", lambda: __import__("server.tracking.data_association"))
    check("server.tracking.track_manager", lambda: __import__("server.tracking.track_manager"))
    check("server.monitoring.node_health", lambda: __import__("server.monitoring.node_health"))
    check("server.security.authenticator", lambda: __import__("server.security.authenticator"))
    check("server.validation.ground_truth", lambda: __import__("server.validation.ground_truth"))
    check("server.validation.calibration_validator", lambda: __import__("server.validation.calibration_validator"))
    check("server.server_main", lambda: __import__("server.server_main"))
    # BUG-009 guard: the actual operator entry point. Importing run_server runs
    # `from server.server_main import main`, so a missing/renamed main() fails
    # here instead of only at deploy time. Previously NOTHING imported it.
    check("run_server (launcher entrypoint)", lambda: __import__("run_server"))
    check("server.server_main.main is callable",
          lambda: callable(__import__("server.server_main", fromlist=["main"]).main))
    check("simulation.sim_node", lambda: __import__("simulation.sim_node"))
    check("simulation.sim_utils", lambda: __import__("simulation.sim_utils"))


def test_protocol():
    """Test protocol pack/unpack round-trip."""
    print("\n=== Phase 2: Protocol Round-Trip ===")
    
    from common.protocol import (
        TelemetryPacket, MotionVector, CommandPacket,
        PACKET_TYPE_TELEMETRY, HEADER_SIZE
    )
    from common.constants import VERSION
    
    # Telemetry packet
    def test_telemetry_roundtrip():
        vectors = [
            MotionVector(azimuth=45.0, elevation=10.0, intensity=200, class_id=1),
            MotionVector(azimuth=90.0, elevation=-5.0, intensity=150, class_id=0),
        ]
        pkt = TelemetryPacket(
            version=VERSION,
            camera_id="cam01",
            timestamp=time.time(),
            sequence_number=42,
            latitude=1.3521,
            longitude=103.8198,
            altitude=15.0,
            orientation=(1.0, 0.0, 0.0, 0.0),
            health_flags=0x07,
            vectors=vectors,
        )
        data = pkt.pack()
        assert len(data) >= HEADER_SIZE, f"Packed data too short: {len(data)}"
        
        pkt2 = TelemetryPacket.unpack(data)
        assert pkt2.camera_id == "cam01", f"Camera ID mismatch: {pkt2.camera_id}"
        assert len(pkt2.vectors) == 2, f"Vector count mismatch: {len(pkt2.vectors)}"
        assert pkt2.sequence_number == 42, f"Sequence mismatch: {pkt2.sequence_number}"
        return True
    
    check("Telemetry pack/unpack (2 vectors)", test_telemetry_roundtrip)
    
    # Command packet
    def test_command_roundtrip():
        cmd = CommandPacket(
            camera_id="cam02",
            command_type=CommandPacket.CMD_RESTART,
            payload=b"\x01\x02\x03",
        )
        data = cmd.pack()
        cmd2 = CommandPacket.unpack(data)
        assert cmd2.camera_id == "cam02"
        assert cmd2.command_type == CommandPacket.CMD_RESTART
        assert cmd2.payload == b"\x01\x02\x03"
        return True
    
    check("Command pack/unpack", test_command_roundtrip)
    
    # Header size (uint16 vector count = 61 bytes)
    def test_header_size():
        assert HEADER_SIZE == 61, f"Expected 61, got {HEADER_SIZE}"
        return True
    
    check("Header size == 61 (uint16 vector_count)", test_header_size)
    
    # Large vector count (>255)
    def test_large_vector_count():
        vectors = [
            MotionVector(azimuth=float(i), elevation=0.0, intensity=100, class_id=0)
            for i in range(300)
        ]
        pkt = TelemetryPacket(
            version=VERSION,
            camera_id="cam03",
            timestamp=time.time(),
            sequence_number=1,
            latitude=0.0, longitude=0.0, altitude=0.0,
            orientation=(1.0, 0.0, 0.0, 0.0),
            health_flags=0x07,
            vectors=vectors,
        )
        data = pkt.pack()
        pkt2 = TelemetryPacket.unpack(data)
        assert len(pkt2.vectors) == 300, f"Expected 300 vectors, got {len(pkt2.vectors)}"
        return True
    
    check("300 vectors (exceeds old uint8 limit)", test_large_vector_count)


def test_config():
    """Test config loading with new GPS/IMU sections."""
    print("\n=== Phase 3: Config ===")
    
    from common.config import Config, GPSConfig, IMUConfig
    
    def test_default_config():
        cfg = Config()
        assert hasattr(cfg, 'gps'), "Missing gps config"
        assert hasattr(cfg, 'imu'), "Missing imu config"
        assert cfg.gps.port == "/dev/serial0"
        assert cfg.imu.i2c_address == 0x68
        return True
    
    check("Config has GPS/IMU sections with defaults", test_default_config)


def test_voxel_grid():
    """Test voxel grid operations."""
    print("\n=== Phase 4: Voxel Grid ===")
    
    import numpy as np
    from server.voxel_grid import VoxelGrid, VoxelGridConfig
    
    def test_grid_lifecycle():
        cfg = VoxelGridConfig(width_m=50, height_m=25, depth_m=50, resolution_m=2.0)
        grid = VoxelGrid(cfg)
        
        # Add a ray
        origin = np.array([0.0, 0.0, 0.0])
        direction = np.array([1.0, 0.0, 0.0])
        direction /= np.linalg.norm(direction)
        updated = grid.add_ray(origin, direction, intensity=10.0)
        assert updated > 0, f"No voxels updated: {updated}"
        
        # Stats
        stats = grid.get_stats()
        assert 'hot_count' in stats, f"Missing hot_count in stats: {stats.keys()}"
        assert 'total_voxels' in stats
        
        # Decay
        grid.decay()
        
        # Detections
        dets = grid.get_detections()
        assert isinstance(dets, list)
        
        return True
    
    check("Grid lifecycle: add_ray -> get_stats -> decay -> get_detections", test_grid_lifecycle)

    def test_ray_pipeline_integration():
        # P0.5: exercise the real build_rays_from_packet -> add_rays_batch handoff
        # which test_grid_lifecycle never touches.
        from server.ray_builder import RayBuilder
        from server.voxel_grid import VoxelGrid, VoxelGridConfig
        from common.protocol import MotionVector

        rb = RayBuilder(reference_lat=1.3521, reference_lon=103.8198, reference_alt=0.0)
        cfg = VoxelGridConfig(width_m=200, height_m=100, depth_m=200, resolution_m=1.0)
        grid = VoxelGrid(cfg)

        vectors = [
            MotionVector(azimuth=45.0, elevation=10.0, intensity=200, class_id=1),
            MotionVector(azimuth=90.0, elevation=5.0,  intensity=180, class_id=1),
        ]
        rays = rb.build_rays_from_packet(
            camera_id="CAM-01",
            latitude=1.3521, longitude=103.8198, altitude=15.0,
            orientation=(1.0, 0.0, 0.0, 0.0),
            vectors=[(v.azimuth, v.elevation, v.intensity) for v in vectors]
        )
        assert len(rays) == 2, f"Expected 2 rays, got {len(rays)}"
        updated = grid.add_rays_batch(rays)
        assert updated >= 0, "add_rays_batch raised or returned negative"
        return True

    check("Ray pipeline: build_rays_from_packet -> add_rays_batch (no TypeError)", test_ray_pipeline_integration)


def test_calibration():
    """Test calibration solver uses gradient descent."""
    print("\n=== Phase 5: Calibration ===")
    
    import numpy as np
    from server.calibration import Calibrator
    
    def test_solver_runs():
        cal = Calibrator(buffer_size=200)
        
        # Feed enough observations to trigger solve
        for i in range(60):
            cal.add_observation(
                camera_id="cam01",
                ray_direction=np.array([1.0, 0.1 * np.sin(i * 0.1), 0.0]),
                camera_position=np.array([0.0, 0.0, 0.0]),
                target_position=np.array([100.0, 5.0, 0.0])
            )
        
        result = cal.solve("cam01")
        assert result is not None, "Solver returned None"
        assert hasattr(result, 'correction_quaternion')
        assert hasattr(result, 'residual_before')
        assert hasattr(result, 'residual_after')
        return True
    
    check("Calibration solver (gradient descent)", test_solver_runs)

    def test_calibration_convergence():
        # P1.5: a consistent, known orientation error converges to ~that offset
        # and the validator approves it.
        from server.calibration import Calibrator
        from server.validation.calibration_validator import CalibrationValidator
        from math_utils.quaternion import from_axis_angle, rotate_vector

        validator = CalibrationValidator(max_correction_degrees=15.0, min_observations=50)
        cal = Calibrator(buffer_size=500, solve_interval=0.0, blend_factor=1.0,
                         validator=validator)
        cam = np.array([0.0, 0.0, 0.0])
        err = from_axis_angle((0, 0, 1), 3.0)  # known 3-degree yaw error
        for i in range(120):
            target = np.array([100.0, (i % 5 - 2) * 2.0, (i % 3 - 1) * 2.0])
            true_dir = target / np.linalg.norm(target)
            measured = np.array(rotate_vector(tuple(true_dir), err))
            cal.add_observation("cam01", measured, target, cam)

        result = cal.solve("cam01")
        assert result is not None, "Solver returned None"
        assert result.residual_after < result.residual_before, "Residual did not improve"
        assert result.approved, f"Correction not approved: {result.reason}"
        assert abs(result.correction_degrees - 3.0) < 1.0, \
            f"Expected ~3deg correction, got {result.correction_degrees:.2f}"
        return True

    check("Calibration converges on a known orientation error (P1.5)",
          test_calibration_convergence)

    def test_calibration_noisy_rejection():
        # P1.5: a correction beyond the validator's threshold is NOT applied.
        from server.calibration import Calibrator
        from server.validation.calibration_validator import CalibrationValidator
        from math_utils.quaternion import from_axis_angle, rotate_vector

        validator = CalibrationValidator(max_correction_degrees=2.0, min_observations=50)
        cal = Calibrator(buffer_size=500, solve_interval=0.0, blend_factor=1.0,
                         validator=validator)
        cam = np.array([0.0, 0.0, 0.0])
        err = from_axis_angle((0, 0, 1), 12.0)  # large error -> large correction
        for i in range(120):
            target = np.array([100.0, (i % 5 - 2) * 2.0, (i % 3 - 1) * 2.0])
            true_dir = target / np.linalg.norm(target)
            measured = np.array(rotate_vector(tuple(true_dir), err))
            cal.add_observation("cam01", measured, target, cam)

        result = cal.solve("cam01")
        assert result is not None, "Solver returned None"
        assert not result.approved, f"Over-threshold correction was approved: {result.reason}"
        # Not applying it leaves the offset at identity.
        assert not cal.apply_correction(result), "Rejected correction was applied"
        return True

    check("Calibration validator rejects over-threshold correction (P1.5)",
          test_calibration_noisy_rejection)

    def test_calibration_feedback_applies_offset():
        # P1.5: the server feedback loop pushes an accepted offset into the
        # node's RayBuilder, verified via get_calibration_offset, and persists it.
        import tempfile
        from server.server_main import OpticalRadarServer
        from math_utils.quaternion import from_axis_angle, rotate_vector

        server = OpticalRadarServer(headless=True)
        tmp = os.path.join(tempfile.gettempdir(), "or_calib_test_offsets.json")
        if os.path.exists(tmp):
            os.remove(tmp)
        server._calibration_offsets_path = tmp
        server.calibrator.solve_interval = 0.0  # force a solve
        server.cluster_manager.assign_node("CAM-01", "DEFAULT")

        cam = np.array([0.0, 0.0, 0.0])
        err = from_axis_angle((0, 0, 1), 3.0)
        for i in range(150):
            target = np.array([100.0, (i % 5 - 2) * 2.0, (i % 3 - 1) * 2.0])
            true_dir = target / np.linalg.norm(target)
            measured = np.array(rotate_vector(tuple(true_dir), err))
            server.calibrator.add_observation("CAM-01", measured, target, cam)

        server._run_calibration()

        cluster = server.cluster_manager.clusters["DEFAULT"]
        offset = cluster.ray_builder.get_calibration_offset("CAM-01")
        assert offset is not None, "Offset not applied to ray_builder"
        assert os.path.exists(tmp), "Offsets were not persisted to disk"
        os.remove(tmp)
        return True

    check("Calibration feedback applies + persists offset via RayBuilder (P1.5)",
          test_calibration_feedback_applies_offset)


def test_tracker():
    """Test tracker pipeline."""
    print("\n=== Phase 6: Tracker ===")
    
    import numpy as np
    from server.tracking.tracker import Tracker
    
    def test_tracker_update():
        tracker = Tracker()
        
        class MockDetection:
            def __init__(self, pos):
                self.position = np.array(pos)
                self.confidence = 1.0
                self.timestamp = time.time()
                self.class_id = 0
        
        # Feed detections over several frames
        for frame in range(10):
            detections = [MockDetection([50.0 + frame, 30.0, 10.0])]
            result = tracker.update(detections)
            assert hasattr(result, 'tracks')
        
        tracks = tracker.get_confirmed_tracks()
        # After 10 frames, should have confirmed at least one track
        # (confirm threshold is typically 3 hits)
        return True
    
    check("Tracker: 10-frame update cycle", test_tracker_update)


def test_full_server_init():
    """Test that server can be initialized without network."""
    print("\n=== Phase 7: Server Initialization ===")
    
    from server.server_main import OpticalRadarServer
    
    def test_server_create():
        server = OpticalRadarServer(headless=True)
        
        # Check all subsystems initialized
        assert server.voxel_grid is not None, "Missing voxel_grid"
        assert server.ray_builder is not None, "Missing ray_builder"
        assert server.tracker is not None, "Missing tracker"
        assert server.calibrator is not None, "Missing calibrator"
        assert server.node_health is not None, "Missing node_health"
        assert server.ground_truth is not None, "Missing ground_truth"
        
        # Check new state variables
        assert hasattr(server, 'current_fps'), "Missing current_fps tracker"
        assert hasattr(server, '_start_time'), "Missing _start_time"
        assert hasattr(server, '_last_frame_time'), "Missing _last_frame_time"
        
        return True
    
    check("Server init (headless, all subsystems present)", test_server_create)


def test_server_process_frame():
    """Test that server can process frames without network."""
    print("\n=== Phase 8: Server Frame Processing ===")
    
    import numpy as np
    from server.server_main import OpticalRadarServer
    
    def test_frame_cycle():
        server = OpticalRadarServer(headless=True)
        
        # Manually add a ray to the voxel grid so there's data to process
        origin = np.array([0.0, 0.0, 0.0])
        direction = np.array([1.0, 0.0, 0.5])
        direction /= np.linalg.norm(direction)
        server.voxel_grid.add_ray(origin, direction, intensity=10.0)
        
        # Process several frames
        for _ in range(5):
            server.process_frame()
        
        # Verify FPS tracking is working
        assert server.current_fps >= 0, f"FPS should be non-negative: {server.current_fps}"
        assert server.frame_count == 5, f"Frame count: {server.frame_count}"
        
        return True
    
    check("5-frame processing cycle (no network)", test_frame_cycle)


def test_simulation_to_server():
    """Test simulation node sends packets that server can unpack."""
    print("\n=== Phase 9: Simulation → Server Pipeline ===")
    
    import numpy as np
    from simulation.sim_node import SimNode, SimCameraConfig, SimTarget
    from common.protocol import TelemetryPacket
    
    def test_sim_packet_creation():
        config = SimCameraConfig(
            camera_id="sim01",
            position=np.array([100.0, 0.0, 2.0]),
            latitude=1.3521,
            longitude=103.8198,
            altitude=15.0,
            fov_horizontal=90.0
        )
        
        node = SimNode(config)
        node.add_target(SimTarget(
            target_id="t1",
            position=np.array([50.0, 50.0, 30.0])
        ))
        
        # Manually call process_frame internals
        detections = node.detect_targets()
        # Whether or not we detect depends on FOV, but the code should not crash
        return True
    
    check("SimNode detect_targets (no crash)", test_sim_packet_creation)


def test_octree():
    """Test hierarchical octree behaviour (P2.1, P2.4-P2.7)."""
    print("\n=== Phase 11: Hierarchical Octree ===")

    import numpy as np
    from server.voxel_grid import VoxelGrid, VoxelGridConfig

    def test_cubic_root_derivation():
        # P2.6: root size = next_pow2(max_dim), regardless of aspect ratio.
        g = VoxelGrid(VoxelGridConfig(width_m=200, depth_m=200, height_m=100))
        assert np.allclose(g._root.size, [256, 256, 256]), f"root size {g._root.size}"
        g2 = VoxelGrid(VoxelGridConfig(width_m=200, depth_m=200, height_m=100,
                                       root_cell_size_m=512))
        assert np.allclose(g2._root.size, [512, 512, 512]), f"override {g2._root.size}"
        return True

    check("Cubic root = next_pow2(max_dim); root_cell_size_m override (P2.6)",
          test_cubic_root_derivation)

    def test_decay_consolidate_independence():
        # P2.1: heat decays per-frame independently of consolidate_and_prune.
        cfg = VoxelGridConfig(width_m=50, height_m=25, depth_m=50, resolution_m=2.0)
        grid = VoxelGrid(cfg)
        grid.add_ray(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]), intensity=10.0)

        heat_before = grid.get_stats()['max_heat']
        for _ in range(10):
            grid.decay_active_leaves()  # no consolidate calls
        heat_after = grid.get_stats()['max_heat']

        expected = heat_before * (0.95 ** 10)
        assert abs(heat_after - expected) < 0.01, \
            f"Heat after 10 decays: {heat_after:.4f}, expected ~{expected:.4f}"
        return True

    check("Decay/consolidate independence: heat = h0 * 0.95^10 (P2.1)",
          test_decay_consolidate_independence)

    def test_amanatides_woo_exact_visit():
        # P2.4: a ray crosses each leaf on its path exactly once (no skip/double).
        # Power-of-2 octree sizing (P2.6) means a uniformly-subdivided 16m root at
        # 2m resolution yields 16/2 = 8 cells along an axis-aligned ray (the
        # plan's literal "50m -> 25 cells" assumed the old dense grid).
        cfg = VoxelGridConfig(root_cell_size_m=16.0, resolution_m=2.0,
                              width_m=16, depth_m=16, height_m=100,
                              min_cameras_to_subdivide=99)
        grid = VoxelGrid(cfg)
        # Uniformly subdivide down to leaf resolution.
        changed = True
        while changed:
            changed = False
            for leaf in list(grid._active_leaves):
                if leaf.size[0] > grid.config.resolution_m:
                    children = leaf.subdivide()
                    grid._active_leaves.discard(leaf)
                    grid._active_leaves.update(children)
                    changed = True

        updated = grid.add_ray(np.array([-10.0, -1.0, 1.0]),
                               np.array([1.0, 0.0, 0.0]), 5.0, max_distance=100.0)
        heated = [l for l in grid._active_leaves if l.heat > 0]
        assert updated == 8, f"Expected 8 leaf visits, got {updated}"
        assert len(heated) == 8, f"Expected 8 distinct heated leaves, got {len(heated)}"
        return True

    check("Ray visits each leaf exactly once (no skip/double-count) (P2.4)",
          test_amanatides_woo_exact_visit)

    def test_subdivision_trigger_camera_count():
        # P2.5: subdivide at M distinct cameras, not at M-1.
        cfg = VoxelGridConfig(width_m=60, depth_m=60, height_m=60, resolution_m=1.0,
                              min_cameras_to_subdivide=3, camera_window_frames=10)
        grid = VoxelGrid(cfg)
        o, d = np.array([0.0, 0.0, 30.0]), np.array([1.0, 0.0, 0.0])
        grid.add_ray(o, d, 10.0, camera_id="C1", frame_index=0)
        grid.add_ray(o, d, 10.0, camera_id="C2", frame_index=0)
        assert len(grid._active_leaves) == 1, "Subdivided at only 2 cameras"
        grid.add_ray(o, d, 10.0, camera_id="C3", frame_index=0)
        assert len(grid._active_leaves) > 1, "Did not subdivide at 3 cameras"
        return True

    check("Subdivision triggers at M cameras, not M-1 (P2.5)",
          test_subdivision_trigger_camera_count)

    def test_subdivision_window_gating():
        # P2.5/OQ1: votes spread beyond the co-temporal window do NOT subdivide.
        cfg = VoxelGridConfig(width_m=60, depth_m=60, height_m=60, resolution_m=1.0,
                              min_cameras_to_subdivide=3, camera_window_frames=10)
        grid = VoxelGrid(cfg)
        o, d = np.array([0.0, 0.0, 30.0]), np.array([1.0, 0.0, 0.0])
        grid.add_ray(o, d, 10.0, camera_id="C1", frame_index=0)
        grid.add_ray(o, d, 10.0, camera_id="C2", frame_index=5)
        grid.add_ray(o, d, 10.0, camera_id="C3", frame_index=20)  # window expired
        assert len(grid._active_leaves) == 1, "Subdivided despite stale camera votes"
        return True

    check("No subdivision when camera votes fall outside the window (P2.5/OQ1)",
          test_subdivision_window_gating)

    def test_root_expansion_preserves_coords():
        # P2.7: existing leaf world coords are unchanged after expand_root.
        cfg = VoxelGridConfig(width_m=50, height_m=50, depth_m=50, resolution_m=5.0)
        grid = VoxelGrid(cfg)
        grid.add_ray(np.array([0.0, 0.0, 25.0]), np.array([1.0, 0.0, 0.0]), intensity=10.0)
        hot_before = grid.get_hot_voxels()
        assert hot_before, "No hot voxels before expansion"
        center_before = hot_before[0].center.copy()

        grid.expand_root(np.array([48.0, 0.0, 25.0]))

        hot_after = grid.get_hot_voxels()
        assert hot_after, "No hot voxels after expansion"
        assert np.allclose(center_before, hot_after[0].center, atol=0.1), \
            f"Leaf moved: {center_before} -> {hot_after[0].center}"
        return True

    check("Root expansion preserves leaf world coordinates (P2.7)",
          test_root_expansion_preserves_coords)


def test_websocket():
    """Test WebSocket rooms + command dispatch + networked packet path (P0.6)."""
    print("\n=== Phase 10: WebSocket Rooms + Commands ===")

    import asyncio
    import json
    from server.websocket_server import WebSocketBroadcaster

    class MockWS:
        def __init__(self):
            self.received = []

        async def send(self, payload):
            self.received.append(payload)

    def test_websocket_rooms():
        b = WebSocketBroadcaster(port=0)
        a_ws, b_ws = MockWS(), MockWS()
        b.clients.update({a_ws, b_ws})
        b.subscribe(a_ws, "A")
        b.subscribe(b_ws, "B")

        payload = json.dumps({"type": "TRACK_UPDATE", "payload": [{"id": "T-1"}]})
        asyncio.run(b._broadcast_async(payload, room="A"))

        assert len(a_ws.received) == 1, f"A should receive 1, got {len(a_ws.received)}"
        assert len(b_ws.received) == 0, f"B should receive 0, got {len(b_ws.received)}"
        return True

    check("WebSocket room isolation (TRACK_UPDATE to room A only)", test_websocket_rooms)

    def test_command_dispatch():
        b = WebSocketBroadcaster(port=0)
        seen = {}

        def handler(client_id, payload):
            seen['cluster_id'] = payload.get('cluster_id')

        b.register_command_handler('CREATE_CLUSTER', handler)
        msg = json.dumps({"type": "CREATE_CLUSTER", "payload": {"cluster_id": "ZONE-1"}})
        asyncio.run(b._on_message(MockWS(), msg))

        assert seen.get('cluster_id') == "ZONE-1", "CREATE_CLUSTER handler not invoked"
        return True

    check("WebSocket command dispatch (CREATE_CLUSTER handler invoked)", test_command_dispatch)

    def test_command_creates_cluster():
        from server.server_main import OpticalRadarServer
        server = OpticalRadarServer(headless=True)
        msg = json.dumps({"type": "CREATE_CLUSTER", "payload": {"cluster_id": "ZONE-9"}})
        asyncio.run(server.ws_server._on_message(MockWS(), msg))
        assert "ZONE-9" in server.cluster_manager.clusters, "Cluster not created via command"
        return True

    check("CREATE_CLUSTER command creates cluster in manager", test_command_creates_cluster)

    def test_process_packet_networked():
        from server.server_main import OpticalRadarServer
        from common.protocol import MotionVector, TelemetryPacket
        server = OpticalRadarServer(headless=True)
        # Bypass signature verification so we exercise the full ray pipeline.
        server.authenticator = None
        server.cluster_manager.assign_node("CAM-01", "DEFAULT")

        pkt = TelemetryPacket(
            camera_id="CAM-01",
            sequence_number=1,
            timestamp=time.time(),
            latitude=1.3521, longitude=103.8198, altitude=15.0,
            orientation=(1.0, 0.0, 0.0, 0.0),
            health_flags=0x07,
            vectors=[MotionVector(azimuth=45.0, elevation=10.0, intensity=200, class_id=1)],
        )
        # End-to-end: build_rays -> add_rays_batch -> broadcast_node_update.
        server._process_packet(pkt, ("127.0.0.1", 5005))
        return True

    check("_process_packet end-to-end (real WebSocketBroadcaster, no AttributeError)",
          test_process_packet_networked)


def test_foxglove():
    """Optional Foxglove/Flora add-on broadcaster (parallel to the JSON one)."""
    print("\n=== Phase 14: Foxglove Broadcaster (optional add-on) ===")

    import numpy as np
    from server.foxglove_broadcaster import FoxgloveBroadcaster, _FG_AVAILABLE

    def test_disabled_is_inert():
        # Always runs: with enabled=False, start()/stop() must be no-ops and the
        # publish_* methods must not raise, whether or not foxglove-sdk is present.
        fg = FoxgloveBroadcaster(port=0, enabled=False)
        fg.start()
        assert not fg.running, "disabled broadcaster must not be running after start()"
        # A publish on a disabled broadcaster is a silent no-op.
        fg.publish_system_status({"server_fps": 30.0})
        fg.stop()
        assert not fg.running
        return True

    check("Disabled broadcaster: start/stop/publish are inert no-ops",
          test_disabled_is_inert)

    def test_enabled_publishes():
        # Exercise the full publish surface with fixtures matching what
        # server_main builds. Only reached when foxglove-sdk is installed.
        from server.voxel_grid import HotVoxel
        from server.ray_builder import Ray

        class _FakeTrack:
            track_id = 7
            state = 1
            position = np.array([10.0, 20.0, 5.0])
            velocity = np.array([1.0, 0.0, 0.0])

        fg = FoxgloveBroadcaster(port=0, enabled=True)
        fg.start()
        assert fg.running, "enabled broadcaster failed to start with sdk present"
        try:
            fg.publish_node_update({
                "id": "CAM-01", "node_id": "CAM-01", "cluster_id": "DEFAULT",
                "location": [1.0, 2.0, 3.0], "status": 0, "battery": None,
                "health_flags": 0x07, "last_seen": time.time(),
            })
            fg.publish_node_location("CAM-01", 37.7749, -122.4194, 10.0)
            fg.publish_system_status({"server_fps": 30.0, "total_tracks": 1})
            fg.publish_clusters({"clusters": {}, "pending_nodes": []})
            fg.publish_scene(
                "DEFAULT",
                [_FakeTrack()],
                [HotVoxel(heat=12.0, center=np.array([3.0, 4.0, 5.0]),
                          level=0, size_m=1.0)],
                [Ray(origin=np.array([0.0, 0.0, 0.0]),
                     direction=np.array([1.0, 0.0, 0.0]),
                     intensity=0.5, camera_id="CAM-01")],
            )
        finally:
            fg.stop()
        return True

    # Gate on the optional dependency: run the real smoke test if installed,
    # otherwise count a single explicit SKIP as a pass (per the add-on contract).
    if _FG_AVAILABLE:
        check("Enabled broadcaster publish smoke test (fixtures match server_main)",
              test_enabled_publishes)
    else:
        global PASS
        PASS += 1
        print("  [PASS] Enabled broadcaster publish smoke test: "
              "SKIPPED (foxglove-sdk not installed)")


def test_regressions():
    """Targeted regression tests for the P0/P1 backend fixes (P4)."""
    print("\n=== Phase 12: Backend Regression Guards ===")

    import numpy as np
    from common.config import Config
    from server.cluster_manager import Cluster
    from server.server_main import OpticalRadarServer
    from common.protocol import MotionVector, TelemetryPacket

    def test_decay_rate_default_in_cluster():
        # P1.2: a Cluster without a decay_rate config entry uses 0.95, not 0.1.
        cluster = Cluster("TEST", Config())
        assert cluster.voxel_grid.config.decay_rate == 0.95, \
            f"decay_rate={cluster.voxel_grid.config.decay_rate}"
        return True

    check("Cluster decay_rate default is 0.95 (P1.2)", test_decay_rate_default_in_cluster)

    def test_hot_threshold_in_cluster():
        # P0.4: hot_threshold from config is honoured (not a dead detection_threshold).
        class FakeConfig:
            voxel_grid = {'hot_threshold': 2.0}
            tracking = None
            simulation = {}
        cluster = Cluster("TEST", FakeConfig())
        assert cluster.voxel_grid.config.hot_threshold == 2.0, \
            f"hot_threshold={cluster.voxel_grid.config.hot_threshold}"
        return True

    check("Cluster honours hot_threshold from config (P0.4)", test_hot_threshold_in_cluster)

    def test_uptime_monotonic():
        # P1.3 + BUG-006: uptime is time-since-start from a MONOTONIC clock, so a
        # wall-clock/NTP step backwards must NOT move it. The old version set
        # _start_time from time.time() and would pass equally whether the code
        # used time.time() or time.monotonic() — i.e. it couldn't catch BUG-006.
        server = OpticalRadarServer(headless=True)
        captured = []
        server.ws_server.broadcast_system_status = lambda d: captured.append(d)

        server._start_time = time.monotonic() - 5.0
        server._broadcast_system_status()

        # Simulate the wall clock stepping back an hour (NTP correction). A
        # monotonic-based uptime is unaffected; a wall-clock one goes negative.
        real_time = time.time
        try:
            time.time = lambda: real_time() - 3600.0
            server._broadcast_system_status()
        finally:
            time.time = real_time

        assert captured[0]['uptime_seconds'] >= 5, f"uptime0={captured[0]['uptime_seconds']}"
        assert captured[1]['uptime_seconds'] >= 5, \
            f"uptime regressed under a wall-clock jump (BUG-006): {captured[1]['uptime_seconds']}"
        return True

    check("Uptime uses a monotonic clock, immune to wall-clock jumps (P1.3/BUG-006)",
          test_uptime_monotonic)

    def test_battery_level_absent():
        # P0.2: _process_packet handles the missing battery_level field (no AttributeError).
        server = OpticalRadarServer(headless=True)
        server.authenticator = None
        server.cluster_manager.assign_node("CAM-01", "DEFAULT")
        captured = []
        server.ws_server.broadcast_node_update = lambda d, room=None: captured.append(d)

        pkt = TelemetryPacket(
            camera_id="CAM-01", sequence_number=1, timestamp=time.time(),
            latitude=1.3521, longitude=103.8198, altitude=15.0,
            orientation=(1.0, 0.0, 0.0, 0.0), health_flags=0x07,
            vectors=[MotionVector(azimuth=10.0, elevation=5.0, intensity=200, class_id=1)],
        )
        server._process_packet(pkt, ("127.0.0.1", 5005))
        # Node updates are coalesced per node and flushed once per frame as a
        # single batched array (broadcast_node_update receives a list).
        server._flush_node_updates()
        assert captured, "No node update broadcast"
        batch = captured[-1]
        assert isinstance(batch, list) and batch, f"expected batched node array, got {batch!r}"
        assert batch[-1]['battery'] is None, "battery should be None (no protocol field)"
        return True

    check("Missing battery_level handled in _process_packet (P0.2)", test_battery_level_absent)

    def test_native_inplace_contract():
        # BUG-003: when the native kernel is active it writes heat IN PLACE.
        # Inject a fake native module to prove native_wrapper hands it the real
        # grid, not a throwaway copy. With the old grid.astype() copy the
        # original is never mutated and these assertions fail. (NATIVE_AVAILABLE
        # is False on this machine, so without the fake this path is untested.)
        from native import native_wrapper as nw

        class _FakeNative:
            def add_ray_to_grid(self, grid, *args):
                grid[0, 0, 0] += 99.0      # in-place write the wrapper must keep
                return 1

            def decay_grid(self, grid, rate):
                grid *= rate

        orig_avail = nw.NATIVE_AVAILABLE
        had_native = hasattr(nw, "_native")
        orig_native = getattr(nw, "_native", None)
        try:
            nw._native = _FakeNative()
            nw.NATIVE_AVAILABLE = True

            grid = np.zeros((4, 4, 4), dtype=np.float32)
            nw.add_ray_to_grid(grid, np.zeros(3), np.array([1.0, 0.0, 0.0]), 5.0)
            assert grid[0, 0, 0] == 99.0, \
                "native write lost: wrapper passed a copy, not the grid (BUG-003)"

            grid[1, 1, 1] = 10.0
            nw.decay_grid(grid, 0.5)
            assert abs(grid[1, 1, 1] - 5.0) < 1e-6, "decay_grid wrote to a copy (BUG-003)"
        finally:
            nw.NATIVE_AVAILABLE = orig_avail
            if had_native:
                nw._native = orig_native
            elif hasattr(nw, "_native"):
                delattr(nw, "_native")
        return True

    check("Native wrapper preserves in-place grid writes (BUG-003)",
          test_native_inplace_contract)

    def test_run_loop_real_tick():
        # Exercise the REAL _run_loop (not just process_frame) for a short burst.
        # Catches contract bugs that live only in the live loop — decay_active_leaves,
        # consolidate gating, get_all_tracks, broadcasts, metrics, calibration gating —
        # which process_frame never touches.
        server = OpticalRadarServer(headless=True)
        server.authenticator = None
        server.cluster_manager.assign_node("CAM-01", "DEFAULT")
        server.voxel_grid.add_ray(np.array([0.0, 0.0, 30.0]),
                                  np.array([1.0, 0.0, 0.0]), intensity=10.0)

        err = []

        def run():
            try:
                server._run_loop()
            except Exception as e:  # noqa: BLE001 - capture for the assertion below
                err.append(e)

        server.running = True
        t = threading.Thread(target=run, daemon=True)
        t.start()
        time.sleep(0.25)
        server.running = False
        t.join(timeout=2.0)

        assert not err, f"_run_loop raised: {err[0]!r}"
        assert not t.is_alive(), "_run_loop did not stop after running=False"
        assert server.frame_count > 0, "loop executed zero frames"
        return True

    check("Real _run_loop runs a burst without raising (closes loop blind spot)",
          test_run_loop_real_tick)

    def test_ground_truth_packet_no_crash():
        # The GT-packet path called a nonexistent process_ground_truth() API and
        # raised AttributeError on every ground-truth packet. Verify a GROUND_TRUTH
        # packet is now recorded via the real add_ground_truth API.
        from common.protocol import PACKET_TYPE_GROUND_TRUTH
        server = OpticalRadarServer(headless=True)
        server.authenticator = None
        ts = time.time()
        gt = TelemetryPacket(
            camera_id="GT", packet_type=PACKET_TYPE_GROUND_TRUTH,
            sequence_number=1, timestamp=ts,
            latitude=1.3521, longitude=103.8198, altitude=20.0,
            orientation=(1.0, 0.0, 0.0, 0.0), health_flags=0,
        )
        server._process_packet(gt, ("127.0.0.1", 5005))
        assert server.gt_evaluator.get_truth_at_time(ts), "ground truth not recorded"
        return True

    check("GROUND_TRUTH packet recorded without AttributeError", test_ground_truth_packet_no_crash)

    def test_server_binds_and_starts():
        # BUG-007: UDPServer(self.config) bound a Config object to the port and
        # crashed on bind in the real start() path — which the rest of the suite
        # never exercises (it calls _run_loop directly). Start the whole server
        # briefly and confirm the UDP socket actually bound.
        server = OpticalRadarServer(headless=True)
        server.authenticator = None
        t = threading.Thread(target=server.start, daemon=True)
        t.start()
        time.sleep(0.4)
        bound = bool(server.udp_server.is_running and server.udp_server._socket is not None)
        server.stop()
        t.join(timeout=2.0)
        assert bound, "UDP server did not bind (BUG-007 regression)"
        return True

    check("Server start() binds the UDP socket (BUG-007 regression)",
          test_server_binds_and_starts)

    def test_cluster_config_wired():
        # #2/#6: the cluster must honour the real `grid` config section and use a
        # non-zero ENU reference origin (the old code read nonexistent
        # `voxel_grid`/`simulation` sections, so grid config was ignored and the
        # origin defaulted to (0,0,0), placing all GPS nodes outside the grid).
        cfg = Config()
        cfg.grid.resolution_m = 4.0
        cluster = Cluster("T", cfg)
        assert cluster.voxel_grid.config.resolution_m == 4.0, "grid config ignored (#6)"
        assert (cluster.ray_builder.ref_lat, cluster.ray_builder.ref_lon) != (0.0, 0.0), \
            "ENU reference origin still (0,0,0) (#2)"
        return True

    check("Cluster honours grid config + non-zero ENU origin (#2/#6)",
          test_cluster_config_wired)

    def test_system_status_keys_match_frontend():
        # BUG-011: the SYSTEM_STATUS payload keys must match the frontend
        # SystemStatus type, or the dashboard reads undefined and shows zeros.
        server = OpticalRadarServer(headless=True)
        captured = []
        server.ws_server.broadcast_system_status = lambda d: captured.append(d)
        server._broadcast_system_status()
        s = captured[0]
        for k in ('server_fps', 'cpu_percent', 'memory_percent',
                  'uptime_seconds', 'total_tracks', 'total_voxels'):
            assert k in s, f"system status missing frontend key '{k}': {list(s)}"
        return True

    check("SYSTEM_STATUS keys match the frontend contract (BUG-011)",
          test_system_status_keys_match_frontend)

    def test_node_status_numeric():
        # #11: node updates carry a numeric NodeHealthStatus (0=HEALTHY), not the
        # string "active" (which never matched the enum, so nodes rendered red).
        server = OpticalRadarServer(headless=True)
        server.authenticator = None
        server.cluster_manager.assign_node("CAM-01", "DEFAULT")
        captured = []
        server.ws_server.broadcast_node_update = lambda d, room=None: captured.append(d)
        pkt = TelemetryPacket(
            camera_id="CAM-01", sequence_number=1, timestamp=time.time(),
            latitude=37.7749, longitude=-122.4194, altitude=10.0,
            orientation=(1.0, 0.0, 0.0, 0.0), health_flags=0x07,
            vectors=[MotionVector(10.0, 5.0, 200, 1)],
        )
        server._process_packet(pkt, ("127.0.0.1", 5005))
        server._flush_node_updates()  # coalesced + flushed once per frame (batched)
        assert captured, "no node update broadcast"
        batch = captured[-1]
        assert isinstance(batch, list) and batch, f"expected batched node array, got {batch!r}"
        assert batch[-1]['status'] == 0, \
            f"expected numeric HEALTHY (0), got {batch[-1]['status']!r}"
        return True

    check("Node update carries numeric health status (#11)", test_node_status_numeric)


def test_security_and_metrics():
    """KeyManager->Authenticator wiring (P5.1) and metrics wiring (P5.2)."""
    print("\n=== Phase 13: Security + Metrics (P5) ===")

    import hmac
    import hashlib
    from server.security.key_manager import KeyManager, KeyMetadata
    from server.security.authenticator import Authenticator
    from common.protocol import MotionVector, TelemetryPacket

    def _signed_packet(key: bytes) -> TelemetryPacket:
        pkt = TelemetryPacket(
            camera_id="CAM-01", sequence_number=1, timestamp=time.time(),
            latitude=0.0, longitude=0.0, altitude=0.0,
            orientation=(1.0, 0.0, 0.0, 0.0), health_flags=0x07,
            vectors=[MotionVector(10.0, 5.0, 200, 1)],
        )
        pkt.signature = hmac.new(key, pkt.get_data_for_signing(), hashlib.sha256).digest()
        return pkt

    def test_key_rotation():
        km = KeyManager()
        k_old = km.generate_key()
        km._keys.append(KeyMetadata(key=k_old, created_at=time.time()))
        auth = Authenticator(key_manager=km)

        assert auth.verify_telemetry_packet(_signed_packet(k_old)), "current key should verify"

        # Rotate: new primary key, old key still valid in the grace window.
        km.rotate_keys(grace_period_days=7)
        k_new = km.primary_key
        assert auth.verify_telemetry_packet(_signed_packet(k_new)), "new key should verify"
        assert auth.verify_telemetry_packet(_signed_packet(k_old)), "old key valid in grace"

        # A foreign key never verifies.
        assert not auth.verify_telemetry_packet(_signed_packet(km.generate_key())), \
            "foreign key must be rejected"

        # Past the grace window, the old key is rejected.
        for meta in km._keys:
            if meta.key == k_old:
                meta.expires_at = time.time() - 1
        assert not auth.verify_telemetry_packet(_signed_packet(k_old)), \
            "expired old key must be rejected"
        return True

    check("Key rotation: grace window + rejection via Authenticator/KeyManager (P5.1)",
          test_key_rotation)

    def test_announce_requires_signature():
        # The announce path must be authenticated when security is on: an unsigned
        # announcement can no longer register/poison a node behind the
        # authenticator (the old hasattr(packet,'signature') gate let it through).
        from server.server_main import OpticalRadarServer
        from common.protocol import AnnouncePacket

        server = OpticalRadarServer(headless=True)
        km = KeyManager()
        key = km.generate_key()
        km._keys.append(KeyMetadata(key=key, created_at=time.time()))
        server.authenticator = Authenticator(key_manager=km)

        # Unsigned announce for a brand-new node -> rejected, no registration.
        unsigned = AnnouncePacket(camera_id="ATTACKER", timestamp=time.time())
        server._process_packet(unsigned, ("10.0.0.9", 5005))
        assert "ATTACKER" not in server._node_optics, "unsigned announce registered a node"
        assert server.cluster_manager.get_cluster_for_node("ATTACKER") is None, \
            "unsigned announce assigned a node to a cluster"

        # A correctly-signed announce IS accepted and registers the node.
        signed = AnnouncePacket(camera_id="REALNODE", timestamp=time.time())
        signed.signature = hmac.new(
            key, signed.get_data_for_signing(), hashlib.sha256).digest()
        server._process_packet(signed, ("10.0.0.10", 5005))
        assert "REALNODE" in server._node_optics, "signed announce failed to register node"
        return True

    check("Announce packets require a valid signature under security (P-sec)",
          test_announce_requires_signature)

    def test_announce_signature_roundtrips_on_wire():
        # A signed announce survives pack(include_signature=True) -> unpack, so the
        # signature travels over the wire and still verifies.
        from common.protocol import AnnouncePacket
        km = KeyManager()
        key = km.generate_key()
        km._keys.append(KeyMetadata(key=key, created_at=time.time()))
        auth = Authenticator(key_manager=km)

        pkt = AnnouncePacket(camera_id="lora20", timestamp=time.time())
        pkt.signature = hmac.new(
            key, pkt.get_data_for_signing(), hashlib.sha256).digest()
        wire = pkt.pack(include_signature=True)
        assert len(wire) == 31 + 32, f"expected 63-byte signed announce, got {len(wire)}"
        rt = AnnouncePacket.unpack(wire)
        assert rt.signature == pkt.signature, "signature did not round-trip"
        assert auth.verify_signed_packet(rt), "round-tripped signed announce failed to verify"
        return True

    check("Signed announce round-trips over the wire and verifies (P-sec)",
          test_announce_signature_roundtrips_on_wire)

    def test_node_registry_bounded():
        # An announce flood (unauthenticated when security is off) must not grow
        # the registry without limit.
        from server.server_main import OpticalRadarServer
        from common.protocol import AnnouncePacket

        server = OpticalRadarServer(headless=True)
        server.authenticator = None  # security off: open registration, but capped
        base = len(server._node_optics)
        server._max_nodes = base + 2
        for i in range(5):
            server._process_packet(
                AnnouncePacket(camera_id=f"n{i}", timestamp=time.time()),
                ("10.0.0.1", 5005))
        assert len(server._node_optics) <= base + 2, \
            f"registry exceeded cap: {len(server._node_optics)} > {base + 2}"
        return True

    check("Node registry is bounded against announce floods (P-sec)",
          test_node_registry_bounded)

    def test_provision_cli_roundtrip():
        import tempfile
        import provision_node
        key_path = os.path.join(tempfile.gettempdir(), "or_provision_test.key")
        if os.path.exists(key_path):
            os.remove(key_path)
        rc = provision_node.main(["--key-file", key_path, "generate"])
        assert rc == 0 and os.path.exists(key_path), "generate failed"
        rc2 = provision_node.main(["--key-file", key_path, "show"])
        assert rc2 == 0, "show failed"
        os.remove(key_path)
        return True

    check("provision_node CLI generate + show round-trip (P5.1)", test_provision_cli_roundtrip)

    def test_metrics_wired():
        from server.server_main import OpticalRadarServer
        from common.protocol import MotionVector, TelemetryPacket
        server = OpticalRadarServer(headless=True)
        server.authenticator = None
        server.metrics.reset()
        server.cluster_manager.assign_node("CAM-01", "DEFAULT")

        pkt = TelemetryPacket(
            camera_id="CAM-01", sequence_number=1, timestamp=time.time(),
            latitude=1.3521, longitude=103.8198, altitude=15.0,
            orientation=(1.0, 0.0, 0.0, 0.0), health_flags=0x07,
            vectors=[MotionVector(10.0, 5.0, 200, 1)],
        )
        server._process_packet(pkt, ("127.0.0.1", 5005))

        snap = server.metrics.snapshot()
        assert snap, "metrics snapshot is empty after processing a packet"
        # The processed-packets counter should be present and >= 1.
        assert any("packets_processed" in k for k in snap), f"missing packet metric: {snap}"
        return True

    check("Metrics recorded + exposed in snapshot after processing (P5.2)", test_metrics_wired)


def test_optics_and_uncertainty():
    print("\n=== Phase 15: Node Optics + Angular Uncertainty ===")
    import numpy as np
    from common.node_specs import load_node_spec, load_all_specs, default_spec
    from server.uncertainty import measurement_covariance
    from server.tracking.kalman_filter import KalmanFilter
    from server.tracking.tracker import Tracker, Detection

    specs_path = os.path.join(code_dir, "config", "node_specs.json")

    def test_spec_file_load():
        # Known node id resolves to its provisioned optics (not a constant).
        cam = load_node_spec("cam01", specs_path)
        assert abs(cam.fov_horizontal - 62.2) < 1e-6, f"cam01 fov: {cam.fov_horizontal}"
        assert cam.resolution_width == 640
        # Unknown id falls back to the file's _default entry.
        unknown = load_node_spec("does-not-exist", specs_path)
        assert abs(unknown.fov_horizontal - 60.0) < 1e-6, f"default fov: {unknown.fov_horizontal}"
        # sigma_theta is a positive, sane per-pixel bearing (< 1 degree here).
        assert 0.0 < cam.sigma_theta_rad < np.radians(1.0), cam.sigma_theta_rad
        assert "cam01" in load_all_specs(specs_path)
        assert "_default" not in load_all_specs(specs_path)  # metadata keys excluded
        return True

    def test_single_camera_is_depth_uncertain():
        # One node at origin looking toward a target 50 m north (+y). Its bearing
        # pins down cross-range (x, z) but barely constrains range (y).
        target = np.array([0.0, 50.0, 0.0])
        sigma = load_node_spec("cam01", specs_path).sigma_theta_rad
        R = measurement_covariance(target, [(np.zeros(3), sigma)])
        assert R is not None and R.shape == (3, 3)
        # Along-range variance (y) must dominate the cross-range variances (x, z).
        assert R[1, 1] > 50.0 * R[0, 0], f"range not dominant: {np.diag(R)}"
        assert R[1, 1] > 50.0 * R[2, 2], f"range not dominant: {np.diag(R)}"
        return True

    def test_two_cameras_triangulate_tighter():
        # Same target, now seen from two well-separated bearings. The fused
        # covariance must be much tighter than either node alone.
        target = np.array([0.0, 50.0, 0.0])
        sigma = load_node_spec("cam01", specs_path).sigma_theta_rad
        cam_a = (np.zeros(3), sigma)              # looks +y
        cam_b = (np.array([50.0, 50.0, 0.0]), sigma)  # looks -x
        R_one = measurement_covariance(target, [cam_a])
        R_two = measurement_covariance(target, [cam_a, cam_b])
        assert R_two is not None
        # Largest positional uncertainty (max eigenvalue) collapses with 2 nodes.
        assert np.max(np.linalg.eigvalsh(R_two)) < 0.25 * np.max(np.linalg.eigvalsh(R_one)), \
            f"triangulation did not tighten: {np.linalg.eigvalsh(R_one)} -> {np.linalg.eigvalsh(R_two)}"
        # No contributing node -> None (tracker will use its default R).
        assert measurement_covariance(target, []) is None
        return True

    def test_kalman_respects_measurement_covariance():
        # A tight R makes the filter trust the measurement (move toward it); a
        # loose R makes it mostly ignore it. Same predicted state, same meas.
        kf = KalmanFilter()
        base = kf.initialize(np.zeros(3))
        pred = kf.predict(base, 0.1)
        meas = np.array([10.0, 0.0, 0.0])
        tight, _ = kf.update(pred, meas, R=np.eye(3) * 0.01)
        loose, _ = kf.update(pred, meas, R=np.eye(3) * 1e4)
        assert tight.position[0] > loose.position[0], \
            f"tight={tight.position[0]:.3f} loose={loose.position[0]:.3f}"
        # Backward compat: update with no R still works (uses filter default).
        default, _ = kf.update(pred, meas)
        assert np.isfinite(default.position).all()
        return True

    def test_covariance_threads_through_tracker():
        # A Detection carrying a covariance must flow through create + update
        # without error and produce a track.
        tracker = Tracker(min_hits_to_confirm=1)
        R = measurement_covariance(
            np.array([0.0, 50.0, 0.0]),
            [(np.zeros(3), 0.002), (np.array([50.0, 50.0, 0.0]), 0.002)],
        )
        det = Detection(position=np.array([0.0, 50.0, 0.0]), covariance=R)
        tracker.update([det], timestamp=100.0)
        tracker.update([det], timestamp=100.1)
        assert len(tracker.get_all_tracks()) >= 1
        return True

    check("Node optics spec loads from file with fallback", test_spec_file_load)
    check("Single-camera covariance is depth-uncertain", test_single_camera_is_depth_uncertain)
    check("Two cameras triangulate to a tighter covariance", test_two_cameras_triangulate_tighter)
    check("Kalman update weights per-measurement R", test_kalman_respects_measurement_covariance)
    check("Detection covariance threads through tracker", test_covariance_threads_through_tracker)


def test_lora_suite():
    print("\n=== Phase 16: LoRa / Meshtastic Suite ===")
    import math
    from common.lora_protocol import (
        LoraAnnouncePacket, LoraUpdatePacket, unpack_lora,
        frame_payload, LoRaFramer, node_id_to_camera_id, camera_id_to_node_id,
        ANNOUNCE_SIZE, UPDATE_SIZE,
    )
    from common.lora_link import LoopbackTransport
    from server.lora_gateway import LoRaGateway
    from common.protocol import AnnouncePacket, TelemetryPacket

    def announce_roundtrip():
        a = LoraAnnouncePacket(node_id=20, lat=37.7749, lon=-122.4194, alt=12.0,
                               roll_deg=1.5, pitch_deg=-3.25, yaw_deg=91.0)
        raw = a.pack()
        assert len(raw) == ANNOUNCE_SIZE, f"len={len(raw)}"
        b = unpack_lora(raw)
        assert isinstance(b, LoraAnnouncePacket) and b.node_id == 20
        assert abs(b.lat - 37.7749) < 1e-3 and abs(b.yaw_deg - 91.0) < 0.02
        return True
    check("LoRa ANNOUNCE pack/unpack round-trip (20 bytes)", announce_roundtrip)

    def update_roundtrip():
        u = LoraUpdatePacket(node_id=20, track_id=7, azimuth=123.4,
                             elevation=-12.0, angular_size=30.0)
        raw = u.pack()
        assert len(raw) == UPDATE_SIZE, f"len={len(raw)}"
        v = unpack_lora(raw)
        assert isinstance(v, LoraUpdatePacket) and v.node_id == 20 and v.track_id == 7
        assert abs(v.azimuth - 123.4) < 0.1 and abs(v.elevation + 12.0) < 1.0
        return True
    check("LoRa UPDATE pack/unpack round-trip (7 bytes)", update_roundtrip)

    check("node id <-> camera id mapping",
          lambda: node_id_to_camera_id(20) == "lora20"
          and camera_id_to_node_id("lora20") == 20)

    def framing_roundtrip():
        a = LoraAnnouncePacket(20, 37.0, -122.0, 5.0, 0, 0, 45.0).pack()
        u = LoraUpdatePacket(20, 1, 90.0, 10.0, 5.0).pack()
        stream = b'\x00\x01garbage' + frame_payload(a) + frame_payload(u)
        framer = LoRaFramer()
        got = []
        for i in range(len(stream)):  # one byte at a time: partial reassembly
            got.extend(framer.push(stream[i:i + 1]))
        assert got == [a, u], f"got {got}"
        return True
    check("LoRaFramer deframes across partial reads + leading garbage", framing_roundtrip)

    def framing_badcrc():
        u = LoraUpdatePacket(20, 1, 90.0, 10.0, 5.0).pack()
        framed = bytearray(frame_payload(u))
        framed[4] ^= 0xFF  # corrupt a payload byte -> CRC mismatch
        assert LoRaFramer().push(bytes(framed)) == []
        return True
    check("LoRaFramer drops a corrupted frame (bad CRC)", framing_badcrc)

    def gateway_translate():
        gw = LoRaGateway(LoopbackTransport(), node_id_prefix="lora")
        gw._ingest(LoraAnnouncePacket(20, 37.7749, -122.4194, 10.0, 0, 0, 90.0).pack(),
                   time.time())
        pkts = gw.get_packets()
        assert len(pkts) == 1
        ann = pkts[0].packet
        assert isinstance(ann, AnnouncePacket) and ann.camera_id == "lora20"
        assert ann.fov_horizontal > 0
        gw._ingest(LoraUpdatePacket(20, 1, 90.0, 10.0, 5.0).pack(), time.time())
        pkts2 = gw.get_packets()
        assert len(pkts2) == 1
        tel = pkts2[0].packet
        assert isinstance(tel, TelemetryPacket) and tel.camera_id == "lora20"
        assert len(tel.vectors) == 1 and abs(tel.latitude - 37.7749) < 1e-3
        q = tel.orientation
        assert abs(math.sqrt(sum(c * c for c in q)) - 1.0) < 1e-6  # normalized quat
        return True
    check("LoRaGateway translates announce->Announce, update->Telemetry", gateway_translate)

    def gateway_orphan():
        gw = LoRaGateway(LoopbackTransport())
        gw._ingest(LoraUpdatePacket(99, 1, 45.0, 0.0, 0.0).pack(), time.time())
        assert gw.get_packets() == []
        assert gw.get_stats()["orphan_updates"] == 1
        return True
    check("LoRaGateway drops update that arrives before any announce", gateway_orphan)

    def gateway_into_server():
        from server.server_main import OpticalRadarServer
        server = OpticalRadarServer(headless=True)
        try:
            gw = LoRaGateway(LoopbackTransport(), node_id_prefix="lora")
            gw._ingest(LoraAnnouncePacket(20, 37.7749, -122.4194, 10.0, 0, 0, 90.0).pack(),
                       time.time())
            gw._ingest(LoraUpdatePacket(20, 1, 90.0, 10.0, 5.0).pack(), time.time())
            for rp in gw.get_packets():
                server._process_packet(rp.packet, (rp.sender_ip, rp.sender_port))
            assert server.cluster_manager.get_cluster_for_node("lora20") is not None
            assert server.ray_builder.get_camera_position("lora20") is not None
        finally:
            server.stop()
        return True
    check("LoRaGateway -> server._process_packet end-to-end (camera registered)",
          gateway_into_server)

    def gateway_threaded():
        radio = LoopbackTransport()
        injector = LoopbackTransport()
        injector.attach_peer(radio)  # injector.send -> radio's inbox -> gw.poll
        gw = LoRaGateway(radio, node_id_prefix="lora")
        gw.start()
        try:
            injector.send(LoraAnnouncePacket(20, 37.0, -122.0, 5.0, 0, 0, 45.0).pack())
            deadline = time.time() + 2.0
            got = []
            while time.time() < deadline and not got:
                got = gw.get_packets()
                if not got:
                    time.sleep(0.02)
            assert got, "gateway thread did not surface the injected announce"
        finally:
            gw.stop()
        return True
    check("LoRaGateway reader thread surfaces injected payloads", gateway_threaded)

    def udp_transport_roundtrip():
        # Mirrors the ESP32-CAM WiFi/UDP backend: a datagram per payload.
        import socket
        from common.lora_link import UDPLoRaTransport
        transport = UDPLoRaTransport(port=5607, bind_addr="127.0.0.1")
        transport.start()
        try:
            cli = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            cli.sendto(LoraAnnouncePacket(20, 37.0, -122.0, 5.0, 0, 0, 45.0).pack(),
                       ("127.0.0.1", 5607))
            deadline = time.time() + 2.0
            got = []
            while time.time() < deadline and not got:
                got = transport.poll()
                if not got:
                    time.sleep(0.02)
            cli.close()
            assert got, "UDP transport did not receive the datagram"
            assert unpack_lora(got[0]) is not None
        finally:
            transport.stop()
        return True
    check("UDPLoRaTransport receives a datagram payload (WiFi backend path)",
          udp_transport_roundtrip)

    def server_lora_integration():
        # Full server wiring: config (env) -> _build_lora_gateway -> start ->
        # inject via the loopback transport -> drain -> _process_packet -> stop.
        os.environ["OR_LORA_ENABLED"] = "true"
        os.environ["OR_LORA_TRANSPORT"] = "loopback"
        try:
            from server.server_main import OpticalRadarServer
            server = OpticalRadarServer(headless=True)
            assert server.lora_server is not None, "gateway not built from config"
            server.lora_server.start()
            try:
                t = server.lora_server.transport
                t.send(LoraAnnouncePacket(21, 37.7749, -122.4194, 10, 0, 0, 90).pack())
                t.send(LoraUpdatePacket(21, 1, 90.0, 10.0, 5.0).pack())
                deadline = time.time() + 2.0
                ok = False
                while time.time() < deadline and not ok:
                    for rp in server.lora_server.get_packets():
                        server._process_packet(rp.packet, (rp.sender_ip, rp.sender_port))
                    ok = (server.cluster_manager.get_cluster_for_node("lora21") is not None
                          and server.ray_builder.get_camera_position("lora21") is not None)
                    if not ok:
                        time.sleep(0.02)
                assert ok, "server did not register the LoRa node end-to-end"
            finally:
                server.stop()
        finally:
            os.environ.pop("OR_LORA_ENABLED", None)
            os.environ.pop("OR_LORA_TRANSPORT", None)
        return True
    check("Server builds+starts LoRa gateway from config and processes a node",
          server_lora_integration)


def main():
    print("=" * 60)
    print("OpticalRadar-Iter3 Full System Orchestration Test")
    print("=" * 60)
    
    test_geo()
    test_quaternion()
    test_imports()
    test_protocol()
    test_config()
    test_voxel_grid()
    test_calibration()
    test_tracker()
    test_full_server_init()
    test_server_process_frame()
    test_simulation_to_server()
    test_octree()
    test_websocket()
    test_regressions()
    test_security_and_metrics()
    test_foxglove()
    test_optics_and_uncertainty()
    test_lora_suite()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed ({PASS + FAIL} total)")
    print("=" * 60)
    
    return FAIL == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
