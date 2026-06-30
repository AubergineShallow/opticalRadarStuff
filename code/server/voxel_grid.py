"""
voxel_grid.py
PURPOSE: 3D grid for accumulating ray intersections.
"""

import numpy as np
from typing import List, Tuple, Optional, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from server.ray_builder import Ray

# Import native acceleration module (with Python fallback)
try:
    import sys
    import os
    _parent = os.path.dirname(os.path.dirname(__file__))
    if _parent not in sys.path:
        sys.path.insert(0, _parent)
    from native import native_wrapper
    _NATIVE_MODULE = native_wrapper
except ImportError:
    _NATIVE_MODULE = None


@dataclass
class VoxelGridConfig:
    """Voxel grid configuration."""
    width_m: float = 200.0  # X (East) dimension
    height_m: float = 100.0  # Z (Up) dimension
    depth_m: float = 200.0  # Y (North) dimension
    resolution_m: float = 1.0  # now means: finest leaf cell size
    decay_rate: float = 0.95  # Per-frame decay
    hot_threshold: float = 5.0  # Minimum heat to consider "hot"

    # --- new optional fields for octree ---
    root_cell_size_m: float = 0.0    # 0.0 -> derive as next_pow2(max(dims)) on init
    level_sizes: tuple = ()          # () -> single-resolution mode (leaf == root_cell_size_m)
    cold_threshold: float = 0.5      # heat below which a leaf is eligible for collapse
    camera_window_frames: int = 10   # co-temporal window for M-distinct-camera trigger
    min_cameras_to_subdivide: int = 3
    camera_window_s: float = 0.5


from dataclasses import field

@dataclass(eq=False)
class OctreeNode:
    bounds_min: np.ndarray      # [xmin, ymin, zmin] world coords
    bounds_max: np.ndarray      # [xmax, ymax, zmax]

    def __hash__(self):
        return id(self)
    heat:       float = 0.0
    level:      int   = 0       # 0 = root
    parent:     Optional['OctreeNode'] = None
    children:   Optional[List[Optional['OctreeNode']]] = None  # None -> leaf

    # Per-node camera tracking
    _recent_cameras: dict = field(default_factory=dict)  # {camera_id: last_frame_index_or_time}

    @property
    def is_leaf(self) -> bool:
        return self.children is None

    @property
    def size(self) -> np.ndarray:
        return self.bounds_max - self.bounds_min

    @property
    def center(self) -> np.ndarray:
        return (self.bounds_min + self.bounds_max) * 0.5

    def subdivide(self) -> List['OctreeNode']:
        """Split into 8 equal children. Returns the new children."""
        mid = self.center
        self.children = []
        for xi in range(2):
            for yi in range(2):
                for zi in range(2):
                    cmin = np.array([
                        self.bounds_min[0] if xi == 0 else mid[0],
                        self.bounds_min[1] if yi == 0 else mid[1],
                        self.bounds_min[2] if zi == 0 else mid[2],
                    ])
                    cmax = np.array([
                        mid[0] if xi == 0 else self.bounds_max[0],
                        mid[1] if yi == 0 else self.bounds_max[1],
                        mid[2] if zi == 0 else self.bounds_max[2],
                    ])
                    child = OctreeNode(
                        bounds_min=cmin, bounds_max=cmax,
                        heat=self.heat / 8.0,   # distribute parent heat
                        level=self.level + 1,
                        parent=self
                    )
                    self.children.append(child)
        return self.children

    def collapse(self) -> None:
        """Merge all children back into parent leaf. Caller updates _active_leaves."""
        self.heat = max((c.heat for c in self.children if c is not None), default=self.heat)
        self.children = None
        self._recent_cameras.clear()


@dataclass
class HotVoxel:
    """Octree-compatible hot-voxel representation."""
    heat:   float
    center: np.ndarray   # world coords — unchanged, still what callers use
    level:  int          # octree depth; 0 = root
    size_m: float        # cell size at this level


class VoxelGrid:
    """
    3D accumulator grid for ray intersection.
    
    Rays from cameras are traced through the grid, adding heat
    to voxels they pass through. Where multiple rays intersect,
    heat accumulates, revealing object locations.
    """
    
    def __init__(self, config: Optional[VoxelGridConfig] = None):
        """
        Initialize voxel grid.
        
        Args:
            config: Grid configuration
        """
        import math
        self.config = config or VoxelGridConfig()
        
        # Derive cubic root size from config (not a hardcoded constant)
        max_dim = max(self.config.width_m, self.config.depth_m, self.config.height_m)

        if self.config.root_cell_size_m > 0:
            root_size = self.config.root_cell_size_m
        else:
            # Round up to next power of two for clean binary subdivision
            root_size = 2 ** math.ceil(math.log2(max_dim)) if max_dim > 0 else 1.0

        # Cubic root centred at (0, 0, root_size/2) so Z starts at ground
        half = root_size / 2.0
        self._root = OctreeNode(
            bounds_min=np.array([-half, -half, 0.0]),
            bounds_max=np.array([ half,  half, root_size]),
            level=0
        )
        self._active_leaves: set = {self._root}
        self._internal_nodes: set = set()

        # Keep dense-grid aliases for backward compat with get_stats() and system_test
        self.nx = int(self.config.width_m / self.config.resolution_m)
        self.ny = int(self.config.depth_m / self.config.resolution_m)
        self.nz = int(self.config.height_m / self.config.resolution_m)
        self.origin = np.array([
            -self.config.width_m / 2,
            -self.config.depth_m / 2,
            0.0
        ])
        
        # Allocate flat grid for compat or hybrid fallback (can be removed later)
        self.grid = np.zeros((self.nx, self.ny, self.nz), dtype=np.float32)
    
    def reset(self) -> None:
        """Clear all heat values."""
        self.grid.fill(0)
        self._active_leaves = {self._root}
        self._internal_nodes.clear()
        self._root.children = None
        self._root.heat = 0.0
    
    def decay_active_leaves(self) -> None:
        """
        Per-frame heat decay. O(active_leaves) multiplications, zero allocation.
        Call every frame from _run_loop at full rate.
        """
        for leaf in self._active_leaves:
            leaf.heat *= self.config.decay_rate

    def consolidate_and_prune(self) -> None:
        """
        Throttled structural housekeeping (1.5s cadence).
        - Collapses sibling leaves that have all cooled below cold_threshold back into parent.
        - Frees OctreeNode objects from the allocator.
        No heat modification; purely structural.
        """
        for node in list(self._internal_nodes):
            if all(c is None or c.heat < self.config.cold_threshold for c in (node.children or [])):
                if node.children:
                    self._active_leaves.difference_update(node.children)
                node.collapse()
                self._active_leaves.add(node)
                self._internal_nodes.discard(node)

    def decay(self) -> None:
        """Backward-compat alias. Prefer decay_active_leaves() directly."""
        self.decay_active_leaves()
    
    def world_to_grid(self, pos: np.ndarray) -> Tuple[int, int, int]:
        """
        Convert world position to grid indices.
        
        Args:
            pos: World position [x, y, z]
        
        Returns:
            Grid indices (ix, iy, iz)
        """
        local = pos - self.origin
        ix = int(local[0] / self.config.resolution_m)
        iy = int(local[1] / self.config.resolution_m)
        iz = int(local[2] / self.config.resolution_m)
        return (ix, iy, iz)
    
    def grid_to_world(self, ix: int, iy: int, iz: int) -> np.ndarray:
        """
        Convert grid indices to world position (voxel center).
        
        Args:
            ix, iy, iz: Grid indices
        
        Returns:
            World position [x, y, z]
        """
        return self.origin + np.array([
            (ix + 0.5) * self.config.resolution_m,
            (iy + 0.5) * self.config.resolution_m,
            (iz + 0.5) * self.config.resolution_m
        ])
    
    def is_valid_index(self, ix: int, iy: int, iz: int) -> bool:
        """Check if indices are within grid bounds."""
        return (0 <= ix < self.nx and 
                0 <= iy < self.ny and 
                0 <= iz < self.nz)
    
    @staticmethod
    def _ray_slab(
        origin: np.ndarray,
        direction: np.ndarray,
        box_min: np.ndarray,
        box_max: np.ndarray,
    ) -> Tuple[float, float]:
        """
        Returns (t_min, t_max) of ray-AABB intersection.
        t_min < 0 means origin is inside the box.
        """
        # Protect against div by zero by temporarily replacing zeros with inf
        inv_dir = np.where(direction != 0, 1.0 / direction, 0)
        t1 = np.where(direction != 0, (box_min - origin) * inv_dir, -np.inf)
        t2 = np.where(direction != 0, (box_max - origin) * inv_dir,  np.inf)
        t_enter = np.minimum(t1, t2).max()
        t_exit  = np.maximum(t1, t2).min()
        return float(t_enter), float(t_exit)

    def _traverse_amanatides_woo(
        self,
        origin: np.ndarray,
        direction: np.ndarray,
        intensity: float,
        camera_id: str,
        frame_index: int,
        max_distance: float,
    ) -> int:
        """
        3D Digital Differential Analyser - exact cell-boundary stepping.
        Traverses the octree coarse-to-fine; subdivides nodes that meet the
        M-distinct-camera threshold.
        """
        direction = direction / np.linalg.norm(direction)
        updated = 0
        stack = [self._root]   # nodes to traverse

        while stack:
            node = stack.pop()

            # Slab intersection test (fast AABB-ray test)
            t_min, t_max = self._ray_slab(origin, direction, node.bounds_min, node.bounds_max)
            if t_max < 0 or t_min > max_distance or t_min > t_max:
                continue

            # Altitude ceiling check (derived from config, not hardcoded)
            if origin[2] + t_min * direction[2] > self.config.height_m:
                continue

            if node.is_leaf:
                node.heat += intensity
                updated += 1

                # Record camera for co-temporal subdivision gating
                import time
                current_time = time.time()
                node._recent_cameras[camera_id] = current_time

                # Prune stale cameras outside co-temporal window
                window_s = self.config.camera_window_s
                node._recent_cameras = {
                    cid: t for cid, t in node._recent_cameras.items()
                    if current_time - t <= window_s
                }

                # Subdivision trigger: M distinct cameras within window AND at fine-enough level
                leaf_size = node.size[0]  # cubic after padding, so all dims equal
                if (len(node._recent_cameras) >= self.config.min_cameras_to_subdivide
                        and leaf_size > self.config.resolution_m):
                    children = node.subdivide()
                    self._internal_nodes.add(node)
                    self._active_leaves.discard(node)
                    self._active_leaves.update(children)
                    stack.extend(children)   # re-traverse children this ray

            else:
                # Internal node: push children that intersect the ray
                stack.extend(c for c in node.children
                             if c is not None and self._ray_slab(origin, direction,
                                               c.bounds_min, c.bounds_max)[0] <= max_distance)

        return updated

    def expand_root(self, breach_position: np.ndarray) -> None:
        """
        Double the octree bounds in the breach direction.
        The old root becomes the child octant opposite to the breach.
        Existing leaf world coordinates are preserved exactly - no translation.
        """
        old_root  = self._root
        old_min   = old_root.bounds_min.copy()
        old_max   = old_root.bounds_max.copy()
        old_size  = old_max - old_min

        # Determine breach direction per axis
        breach_positive = breach_position > (old_min + old_size * 0.9)
        breach_negative = breach_position < (old_min + old_size * 0.1)

        new_min = old_min.copy()
        new_max = old_max.copy()

        for axis in range(3):
            if breach_positive[axis]:
                new_max[axis] += old_size[axis]      # extend in +axis
            elif breach_negative[axis]:
                new_min[axis] -= old_size[axis]       # extend in -axis

        super_root = OctreeNode(
            bounds_min=new_min,
            bounds_max=new_max,
            level=old_root.level - 1,
            children=[None] * 8
        )

        # Place old root in the child octant opposite the breach direction
        # (so existing leaves remain valid with no coordinate shift)
        octant_idx = sum(
            (1 if not breach_positive[ax] and not breach_negative[ax]
               else (0 if breach_positive[ax] else 1)) << ax
            for ax in range(3)
        )
        super_root.children[octant_idx] = old_root
        old_root.parent = super_root
        self._internal_nodes.add(super_root)
        self._root = super_root

    def add_ray(
        self,
        origin: np.ndarray,
        direction: np.ndarray,
        intensity: float = 1.0,
        max_distance: float = 150.0,
        step_size: float = 0.5,
        camera_id: str = "UNKNOWN",
        frame_index: int = 0
    ) -> int:
        """
        Add heat along a ray using Amanatides-Woo.
        """
        if _NATIVE_MODULE is not None:
            pass # Phase 2 natively
            
        return self._traverse_amanatides_woo(
            origin, direction, intensity, camera_id, frame_index, max_distance
        )
    
    def add_rays_batch(
        self,
        rays: List['Ray'],
        max_distance: float = 150.0,
        step_size: float = 0.5
    ) -> int:
        """
        Add multiple rays efficiently.
        
        Uses native C++ batch processing when available for maximum performance.
        
        Args:
            rays: List of Ray objects
            max_distance: Maximum ray distance
        
        Returns:
            Total voxels updated
        """
        if not rays:
            return 0
        
        # Use native batch processing if available
        if _NATIVE_MODULE is not None:
            # Phase 1: octree traversal is Python-only
            # Phase 2: add native octree traversal kernel here once profiled
            pass
        
        # Python fallback
        total = 0
        import server.server_main # To get frame_count? No, let's just use 0 or pass it if possible
        for r in rays:
            total += self.add_ray(
                r.origin,
                r.direction,
                r.intensity,
                max_distance,
                step_size,
                camera_id=r.camera_id,
                # For frame_index we would need it passed down, but for now 0 is fine since we use time.time() in Amanatides-Woo anyway.
                frame_index=0
            )
        return total
    
    def get_hot_voxels(
        self,
        threshold: Optional[float] = None
    ) -> List[HotVoxel]:
        """
        Find voxels above heat threshold.
        
        Args:
            threshold: Heat threshold (default: config value)
        
        Returns:
            List of hot voxels
        """
        threshold = threshold if threshold is not None else self.config.hot_threshold
        results = [
            HotVoxel(heat=leaf.heat, center=leaf.center,
                     level=leaf.level, size_m=float(leaf.size[0]))
            for leaf in self._active_leaves
            if leaf.heat >= threshold
        ]
        results.sort(key=lambda v: v.heat, reverse=True)
        return results
    
    def cluster_hot_voxels(
        self,
        hot_voxels: List[HotVoxel],
        cluster_radius: float = 3.0
    ) -> List[np.ndarray]:
        """
        Cluster nearby hot voxels into detection centroids.
        
        Args:
            hot_voxels: List of hot voxels
            cluster_radius: Maximum distance for clustering
        
        Returns:
            List of cluster center positions
        """
        if not hot_voxels:
            return []
        
        clusters = []
        used = [False] * len(hot_voxels)
        
        for i, voxel in enumerate(hot_voxels):
            if used[i]:
                continue
            
            # Start new cluster
            cluster_positions = [voxel.center]
            cluster_weights = [voxel.heat]
            used[i] = True
            
            # Find neighbors
            for j, other in enumerate(hot_voxels[i+1:], i+1):
                if used[j]:
                    continue
                
                dist = np.linalg.norm(voxel.center - other.center)
                if dist <= cluster_radius:
                    cluster_positions.append(other.center)
                    cluster_weights.append(other.heat)
                    used[j] = True
            
            # Weighted centroid
            weights = np.array(cluster_weights)
            positions = np.array(cluster_positions)
            centroid = np.average(positions, axis=0, weights=weights)
            clusters.append(centroid)
        
        return clusters
    
    def get_detections(
        self,
        threshold: Optional[float] = None,
        cluster_radius: float = 3.0
    ) -> List[np.ndarray]:
        """
        Get detection positions from current grid state.
        
        Args:
            threshold: Heat threshold
            cluster_radius: Clustering radius
        
        Returns:
            List of detection positions
        """
        hot = self.get_hot_voxels(threshold)
        return self.cluster_hot_voxels(hot, cluster_radius)
    
    def get_stats(self) -> dict:
        """Get grid statistics."""
        return {
            'dimensions':               (self.nx, self.ny, self.nz),    # kept for compat
            'total_voxels':             len(self._active_leaves),       # NOW: active leaf count
            'max_resolution_total_voxels': self.nx * self.ny * self.nz, # old dense-equivalent
            'max_heat':                 max((l.heat for l in self._active_leaves), default=0.0),
            'hot_count':                sum(1 for l in self._active_leaves
                                            if l.heat >= self.config.hot_threshold),
        }
