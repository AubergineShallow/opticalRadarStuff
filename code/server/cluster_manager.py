import math
import numpy as np
from typing import Dict, List, Optional, Tuple, Set
from .voxel_grid import VoxelGrid, VoxelGridConfig
from .ray_builder import RayBuilder
from .tracking.tracker import Tracker
from math_utils.geo import haversine_distance


def _cfg_get(section, key, default):
    """Read a field from a config section that may be a dataclass, dict, or None.

    The real Config exposes dataclass sections (e.g. ``grid``); some test fakes
    pass dict-style sections (e.g. ``voxel_grid={'hot_threshold': 2.0}``). This
    tolerates both so the cluster honours whichever config shape it is given.
    """
    if section is None:
        return default
    if isinstance(section, dict):
        return section.get(key, default)
    return getattr(section, key, default)


class Cluster:
    def __init__(self, cluster_id: str, config: 'Config'):
        self.cluster_id = cluster_id

        # Grid config: prefer the real `grid` (GridConfig) section; fall back to
        # a dict-style `voxel_grid` (test fakes), else built-in defaults. The old
        # code only looked for `voxel_grid`, which the real Config never has, so
        # every `grid:` setting from config.yaml was silently ignored.
        grid_section = getattr(config, 'grid', None)
        if grid_section is None:
            grid_section = getattr(config, 'voxel_grid', None)
        vg_config = VoxelGridConfig()
        vg_config.width_m = _cfg_get(grid_section, 'width_m', 200.0)
        vg_config.height_m = _cfg_get(grid_section, 'height_m', 100.0)
        vg_config.depth_m = _cfg_get(grid_section, 'depth_m', 200.0)
        vg_config.resolution_m = _cfg_get(grid_section, 'resolution_m', 1.0)
        # P1.2: decay_rate default 0.95 (half-life ~14 frames @30Hz).
        vg_config.decay_rate = _cfg_get(grid_section, 'decay_rate', 0.95)
        # P0.4: the field is hot_threshold, not detection_threshold.
        vg_config.hot_threshold = _cfg_get(grid_section, 'hot_threshold', 5.0)
        # Leaf ceiling (memory + traversal-cost guard). Falls back to the
        # VoxelGridConfig default when the section doesn't specify it.
        vg_config.max_active_leaves = _cfg_get(
            grid_section, 'max_active_leaves', vg_config.max_active_leaves)
        self.voxel_grid = VoxelGrid(vg_config)

        # ENU reference origin: prefer the real `reference` section; fall back to
        # a dict-style `simulation` section (test fakes), else the SF default the
        # frontend also uses. A (0,0,0) origin placed every realistic GPS node
        # thousands of km outside the grid, so no target was ever tracked.
        ref_section = getattr(config, 'reference', None)
        if ref_section is None:
            ref_section = getattr(config, 'simulation', None)
        ref_lat = _cfg_get(ref_section, 'origin_lat', 37.7749)
        ref_lon = _cfg_get(ref_section, 'origin_lon', -122.4194)
        ref_alt = _cfg_get(ref_section, 'origin_alt', 0.0)
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

        # Pending nodes that have connected but are not assigned to a cluster.
        # Bounded: unauthenticated telemetry/announces with unique camera_ids
        # register here as a side effect of get_cluster_for_node(), so an
        # unbounded set is a trivial memory/broadcast-size DoS.
        self.pending_nodes: Set[str] = set()
        net_cfg = getattr(config, 'network', None)
        self.max_pending_nodes: int = _cfg_get(net_cfg, 'max_nodes', 256)

        # Upper bound on distinct clusters. Each cluster allocates a full voxel
        # grid + tracker + ray builder, so an unauthenticated WebSocket client
        # spamming CREATE_CLUSTER could otherwise exhaust memory/CPU. The reserved
        # DEFAULT cluster always fits under the cap.
        self.max_clusters: int = _cfg_get(net_cfg, 'max_clusters', 64)

        # Default fallback cluster if auto-create is enabled, or explicit creation
        self.create_cluster('DEFAULT')

    def create_cluster(self, cluster_id: str) -> Optional[Cluster]:
        """Create (or return existing) cluster, or None if the cap is hit.

        Returns the existing cluster when the id is already known, a new cluster
        when there is room, and None when creating a new one would exceed
        max_clusters (so callers can reject the request instead of growing
        memory without limit).
        """
        if cluster_id in self.clusters:
            return self.clusters[cluster_id]
        if len(self.clusters) >= self.max_clusters:
            return None
        self.clusters[cluster_id] = Cluster(cluster_id, self.config)
        return self.clusters[cluster_id]

    def assign_node(self, node_id: str, cluster_id: str) -> bool:
        """Assigns a node to a specific cluster."""
        if cluster_id not in self.clusters:
            return False

        # Remove from previous cluster if necessary. Also purge the node's
        # camera state from the old cluster's ray builder, or its (now stale)
        # position keeps feeding that cluster's measurement covariance.
        old_cluster_id = self.node_assignments.get(node_id)
        if old_cluster_id and old_cluster_id in self.clusters:
            old_cluster = self.clusters[old_cluster_id]
            old_cluster.assigned_nodes.discard(node_id)
            remove = getattr(old_cluster.ray_builder, 'remove_camera', None)
            if remove:
                remove(node_id)

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

        # Register as pending if not assigned (bounded; see __init__)
        if node_id not in self.pending_nodes and \
                len(self.pending_nodes) < self.max_pending_nodes:
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
