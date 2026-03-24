"""
voxel_grid.py
PURPOSE: 2D grid for accumulating ray intersections (2D fork).

The 3D voxel grid has been replaced with a 2D occupancy grid.
Rays are projected onto the ground plane before being traced.

Ghost-track prevention: cells require rays from >= min_cameras distinct
cameras before qualifying as "hot" detections.
"""

import numpy as np
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict

import sys
import os
_parent = os.path.dirname(os.path.dirname(__file__))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

# Native acceleration (3D wrapper shimmed to 2D)
try:
    from native import native_wrapper
    _NATIVE_AVAILABLE = native_wrapper.NATIVE_AVAILABLE
except ImportError:
    _NATIVE_AVAILABLE = False


@dataclass
class VoxelGridConfig:
    """2D grid configuration."""
    width_m: float = 200.0       # X (East) dimension
    depth_m: float = 200.0       # Y (North) dimension
    resolution_m: float = 1.0    # Cell size
    decay_rate: float = 0.95     # Per-frame decay
    hot_threshold: float = 5.0   # Minimum heat to consider "hot"
    min_cameras: int = 2         # Minimum distinct cameras for valid detection
    contributor_ttl: int = 30    # Frames before a camera contribution expires


@dataclass
class HotCell:
    """A grid cell above the heat threshold (2D)."""
    x: int
    y: int
    heat: float
    center: np.ndarray  # Center position in world coords [x, y]


class VoxelGrid:
    """
    2D accumulator grid for ray intersection (2D fork).

    Rays from cameras are projected onto the ground plane and traced
    through the grid, adding heat to cells they pass through. Where
    multiple rays intersect, heat accumulates, revealing object locations.
    """

    def __init__(self, config: Optional[VoxelGridConfig] = None):
        """
        Initialize 2D grid.

        Args:
            config: Grid configuration
        """
        self.config = config or VoxelGridConfig()

        # Calculate grid dimensions
        self.nx = int(self.config.width_m / self.config.resolution_m)
        self.ny = int(self.config.depth_m / self.config.resolution_m)

        # Grid origin (center of grid at ground level)
        self.origin = np.array([
            -self.config.width_m / 2,
            -self.config.depth_m / 2,
        ])

        # Allocate 2D grid
        self.grid = np.zeros((self.nx, self.ny), dtype=np.float32)

        # Camera contributor tracking (ghost-track prevention)
        # Maps (ix, iy) -> {camera_id: frames_remaining}
        self._contributors: Dict[Tuple[int, int], Dict[str, int]] = defaultdict(dict)

        # Frame counter for contributor aging
        self._frame_count: int = 0

    def reset(self) -> None:
        """Clear all heat values and contributor tracking."""
        self.grid.fill(0)
        self._contributors.clear()
        self._frame_count = 0

    def decay(self) -> None:
        """Apply decay to all cells and age contributor records."""
        self.grid *= self.config.decay_rate
        self._frame_count += 1

        # Age out stale contributors
        stale_cells = []
        for cell_key, cameras in self._contributors.items():
            expired = [cid for cid, ttl in cameras.items() if ttl <= self._frame_count]
            for cid in expired:
                del cameras[cid]
            if not cameras:
                stale_cells.append(cell_key)
        for key in stale_cells:
            del self._contributors[key]

    def world_to_grid(self, pos: np.ndarray) -> Tuple[int, int]:
        """
        Convert world position to grid indices (2D).

        Args:
            pos: World position [x, y] (or [x, y, …] — extra dims ignored)

        Returns:
            Grid indices (ix, iy)
        """
        local = pos[:2] - self.origin
        ix = int(local[0] / self.config.resolution_m)
        iy = int(local[1] / self.config.resolution_m)
        return (ix, iy)

    def grid_to_world(self, ix: int, iy: int) -> np.ndarray:
        """
        Convert grid indices to world position (cell center, 2D).

        Args:
            ix, iy: Grid indices

        Returns:
            World position [x, y]
        """
        return self.origin + np.array([
            (ix + 0.5) * self.config.resolution_m,
            (iy + 0.5) * self.config.resolution_m,
        ])

    def is_valid_index(self, ix: int, iy: int) -> bool:
        """Check if indices are within grid bounds."""
        return (0 <= ix < self.nx and
                0 <= iy < self.ny)

    def add_ray(
        self,
        origin: np.ndarray,
        direction: np.ndarray,
        intensity: float = 1.0,
        max_distance: float = 150.0,
        step_size: float = 0.5,
        camera_id: str = ""
    ) -> int:
        """
        Add heat along a ray (projected to 2D ground plane).

        Args:
            origin: Ray origin [x, y] (or [x,y,z] – z ignored)
            direction: Ray direction (unit vector, [x,y] or [x,y,z] – z ignored)
            intensity: Heat to add per cell
            max_distance: Maximum ray distance
            step_size: March step size
            camera_id: Source camera identifier (for ghost-track prevention)

        Returns:
            Number of cells updated
        """
        # Project to 2D
        o2 = np.array(origin[:2], dtype=np.float64)
        d2 = np.array(direction[:2], dtype=np.float64)
        norm = np.linalg.norm(d2)
        if norm < 1e-12:
            return 0
        d2 = d2 / norm

        # Try native acceleration via 3D shim
        if _NATIVE_AVAILABLE:
            return self._add_ray_native(o2, d2, intensity, max_distance, step_size, camera_id)

        # Pure Python fallback (Vectorized with NumPy)
        ttl = self._frame_count + self.config.contributor_ttl

        # Precompute all t values
        t_vals = np.arange(0, max_distance, step_size)

        # Calculate all positions [N, 2]
        positions = o2 + t_vals[:, np.newaxis] * d2

        # Convert to grid indices [N]
        ixs = ((positions[:, 0] - self.origin[0]) / self.config.resolution_m).astype(int)
        iys = ((positions[:, 1] - self.origin[1]) / self.config.resolution_m).astype(int)

        # Filter valid indices
        valid = (ixs >= 0) & (ixs < self.nx) & (iys >= 0) & (iys < self.ny)
        valid_ixs = ixs[valid]
        valid_iys = iys[valid]

        if len(valid_ixs) == 0:
            return 0

        # Add heat
        np.add.at(self.grid, (valid_ixs, valid_iys), intensity)

        # Track contributors
        if camera_id:
            # Extract unique cells touched by the ray to ensure all are tracked
            unique_cells = np.unique(np.column_stack((valid_ixs, valid_iys)), axis=0)
            for ix, iy in unique_cells:
                self._contributors[(ix, iy)][camera_id] = ttl

        return len(valid_ixs)

    def _add_ray_native(
        self,
        o2: np.ndarray,
        d2: np.ndarray,
        intensity: float,
        max_distance: float,
        step_size: float,
        camera_id: str
    ) -> int:
        """
        Native-accelerated ray marching via 3D shim.

        Expands the 2D grid to a thin 3D slab (nz=1), runs the native
        C++ kernel, then copies heat values back to the 2D grid.
        """
        # Expand to 3D: shape (nx, ny) -> (nx, ny, 1)
        grid_3d = self.grid[:, :, np.newaxis].copy().astype(np.float32)
        origin_3d = np.array([o2[0], o2[1], 0.0])
        dir_3d = np.array([d2[0], d2[1], 0.0])
        grid_origin_3d = np.array([self.origin[0], self.origin[1], -0.5])

        updated = native_wrapper.add_ray_to_grid(
            grid_3d, origin_3d, dir_3d, intensity,
            step_size, max_distance, self.config.resolution_m,
            grid_origin_3d
        )

        # Copy heat back to 2D grid
        self.grid[:, :] = grid_3d[:, :, 0]

        # Track contributors (still Python — contributor map is lightweight)
        if camera_id:
            ttl = self._frame_count + self.config.contributor_ttl
            t = 0.0
            while t < max_distance:
                pos = o2 + t * d2
                ix = int((pos[0] - self.origin[0]) / self.config.resolution_m)
                iy = int((pos[1] - self.origin[1]) / self.config.resolution_m)
                if self.is_valid_index(ix, iy):
                    self._contributors[(ix, iy)][camera_id] = ttl
                t += step_size * 5  # Coarser step for contributor tracking (perf)

        return updated

    def add_rays_batch(
        self,
        rays: List[Tuple[np.ndarray, np.ndarray, float]],
        max_distance: float = 150.0,
        step_size: float = 0.5
    ) -> int:
        """
        Add multiple rays efficiently.

        Args:
            rays: List of (origin, direction, intensity) tuples
            max_distance: Maximum ray distance

        Returns:
            Total cells updated
        """
        if not rays:
            return 0

        total = 0
        for origin, direction, intensity in rays:
            total += self.add_ray(origin, direction, intensity, max_distance, step_size)
        return total

    def _camera_count(self, ix: int, iy: int) -> int:
        """Get number of distinct cameras contributing to a cell."""
        return len(self._contributors.get((ix, iy), {}))

    def get_hot_cells(
        self,
        threshold: Optional[float] = None,
        min_cameras: Optional[int] = None
    ) -> List[HotCell]:
        """
        Find cells above heat threshold with sufficient camera diversity.

        Args:
            threshold: Heat threshold (default: config value)
            min_cameras: Minimum distinct cameras (default: config value)

        Returns:
            List of hot cells meeting both criteria
        """
        threshold = threshold or self.config.hot_threshold
        min_cameras = min_cameras if min_cameras is not None else self.config.min_cameras

        hot_indices = np.argwhere(self.grid >= threshold)

        results = []
        for ix, iy in hot_indices:
            # Ghost-track prevention: require multi-camera evidence
            if self._camera_count(ix, iy) < min_cameras:
                continue

            results.append(HotCell(
                x=ix,
                y=iy,
                heat=float(self.grid[ix, iy]),
                center=self.grid_to_world(ix, iy)
            ))

        # Sort by heat (descending)
        results.sort(key=lambda v: v.heat, reverse=True)

        return results

    # Alias so that callers using the old 3D name still work
    get_hot_voxels = get_hot_cells

    def cluster_hot_cells(
        self,
        hot_cells: List[HotCell],
        cluster_radius: float = 3.0
    ) -> List[np.ndarray]:
        """
        Cluster nearby hot cells into detection centroids.

        Args:
            hot_cells: List of hot cells
            cluster_radius: Maximum distance for clustering

        Returns:
            List of cluster center positions [x, y]
        """
        if not hot_cells:
            return []

        clusters = []
        used = [False] * len(hot_cells)

        for i, cell in enumerate(hot_cells):
            if used[i]:
                continue

            cluster_positions = [cell.center]
            cluster_weights = [cell.heat]
            used[i] = True

            for j, other in enumerate(hot_cells[i+1:], i+1):
                if used[j]:
                    continue

                dist = np.linalg.norm(cell.center - other.center)
                if dist <= cluster_radius:
                    cluster_positions.append(other.center)
                    cluster_weights.append(other.heat)
                    used[j] = True

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
            List of detection positions [x, y]
        """
        hot = self.get_hot_cells(threshold)
        return self.cluster_hot_cells(hot, cluster_radius)

    def get_stats(self) -> dict:
        """Get grid statistics."""
        hot_indices = np.argwhere(self.grid >= self.config.hot_threshold)
        hot_heat = len(hot_indices)
        hot_multi = sum(
            1 for ix, iy in hot_indices
            if self._camera_count(ix, iy) >= self.config.min_cameras
        )
        return {
            'dimensions': (self.nx, self.ny),
            'total_cells': self.nx * self.ny,
            'max_heat': float(self.grid.max()),
            'mean_heat': float(self.grid.mean()),
            'hot_count_heat_only': hot_heat,
            'hot_count_verified': hot_multi,
            'tracked_cells': len(self._contributors),
            'native_accel': _NATIVE_AVAILABLE,
        }
