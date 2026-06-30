
import math
import numpy as np
from typing import Dict, List, Optional, Tuple, Set
from .voxel_grid import VoxelGrid, VoxelGridConfig
from .ray_builder import RayBuilder
from .tracking.tracker import Tracker
from math_utils.geo import haversine_distance

class Cluster:
    def __init__(self, cluster_id: str, config: 'Config'):
        self.cluster_id = cluster_id

        # Isolated processing instances for this cluster
        vg_config_dict = getattr(config, 'voxel_grid', {})
        if not isinstance(vg_config_dict, dict):
            vg_config_dict = {}
        vg_config = VoxelGridConfig()
        vg_config.width_m = vg_config_dict.get('width_m', 200.0)
        vg_config.height_m = vg_config_dict.get('height_m', 100.0)
        vg_config.depth_m = vg_config_dict.get('depth_m', 200.0)
        vg_config.resolution_m = vg_config_dict.get('resolution_m', 1.0)
        # P1.2: VoxelGridConfig.decay_rate default is 0.95 (half-life ~14 frames).
        # 0.1 made the accumulator nearly useless (heat halved in ~2 frames @30Hz).
        vg_config.decay_rate = vg_config_dict.get('decay_rate', 0.95)
        # P0.4: the field is hot_threshold, not detection_threshold. Writing
        # detection_threshold silently created a dead attribute nothing reads.
        vg_config.hot_threshold = vg_config_dict.get('hot_threshold', 5.0)
        self.voxel_grid = VoxelGrid(vg_config)

        sim_config = getattr(config, 'simulation', {})
        if not isinstance(sim_config, dict):
            sim_config = {}
        ref_lat = sim_config.get('origin_lat', 0.0)
        ref_lon = sim_config.get('origin_lon', 0.0)
        ref_alt = sim_config.get('origin_alt', 0.0)
        self.ray_builder = RayBuilder(ref_lat, ref_lon, ref_alt)

        # Tracker takes individual solver parameters, not a Config object (same
        # bug class as P1.1's Calibrator(self.config)). Map the tracking config
        # section onto the constructor; fall back to defaults if absent.
        tracking_cfg = getattr(config, 'tracking', None)
        if tracking_cfg is not None and not isinstance(tracking_cfg, dict):
            self.tracker = Tracker(
                distance_threshold=tracking_cfg.distance_threshold_m,
                min_hits_to_confirm=tracking_cfg.min_hits_to_confirm,
                max_misses_to_delete=tracking_cfg.max_misses_to_delete,
                max_tracks=tracking_cfg.max_tracks,
                q_process_noise=tracking_cfg.q_process_noise,
                r_measurement_noise=tracking_cfg.r_measurement_noise,
            )
        else:
            self.tracker = Tracker()

        # Nodes explicitly assigned to this cluster
        self.assigned_nodes: Set[str] = set()

class ClusterManager:
    """
    Manages multiple independent tracking clusters/domains.
    Routes telemetry to the correct cluster and handles node assignment.
    """
    def __init__(self, config: 'Config'):
        self.config = config
        self.clusters: Dict[str, Cluster] = {}

        # Map of node_id -> assigned cluster_id
        self.node_assignments: Dict[str, str] = {}

        # Pending nodes that have connected but are not assigned to a cluster
        self.pending_nodes: Set[str] = set()

        # Default fallback cluster if auto-create is enabled, or explicit creation
        self.create_cluster('DEFAULT')

    def create_cluster(self, cluster_id: str) -> Cluster:
        if cluster_id not in self.clusters:
            self.clusters[cluster_id] = Cluster(cluster_id, self.config)
        return self.clusters[cluster_id]

    def assign_node(self, node_id: str, cluster_id: str) -> bool:
        """Assigns a node to a specific cluster."""
        if cluster_id not in self.clusters:
            return False

        # Remove from previous cluster if necessary
        old_cluster_id = self.node_assignments.get(node_id)
        if old_cluster_id and old_cluster_id in self.clusters:
            self.clusters[old_cluster_id].assigned_nodes.discard(node_id)

        self.node_assignments[node_id] = cluster_id
        self.clusters[cluster_id].assigned_nodes.add(node_id)

        if node_id in self.pending_nodes:
            self.pending_nodes.remove(node_id)

        return True

    def get_cluster_for_node(self, node_id: str) -> Optional[Cluster]:
        """Returns the cluster assigned to this node, or None if unassigned."""
        cluster_id = self.node_assignments.get(node_id)
        if cluster_id:
            return self.clusters.get(cluster_id)

        # Register as pending if not assigned
        if node_id not in self.pending_nodes:
            self.pending_nodes.add(node_id)

        return None

    def get_all_clusters(self) -> Dict[str, Cluster]:
        return self.clusters

    def calculate_effective_volume(self, cluster_id: str) -> float:
        """
        Calculates the effective monitoring volume of a cluster.
        Effective volume is defined as the number of voxels visible by >= 2 cameras
        in the cluster, multiplied by the volume of a single voxel.
        """
        cluster = self.clusters.get(cluster_id)
        if not cluster or len(cluster.assigned_nodes) < 2:
            return 0.0

        grid = cluster.voxel_grid

        # For a true implementation, we would raycast from every camera to every voxel
        # to check frustum intersection.
        # As a placeholder/simplified calculation for the current step:
        # P0.3: VoxelGridConfig field is resolution_m, not resolution.
        voxel_vol = grid.config.resolution_m ** 3

        # Assume each camera covers ~1000 voxels, and intersection is roughly 20%
        # This will be replaced with true geometric projection later.
        num_cameras = len(cluster.assigned_nodes)
        if num_cameras >= 2:
            estimated_effective_voxels = (num_cameras * 1000) * 0.20
            return estimated_effective_voxels * voxel_vol

        return 0.0
