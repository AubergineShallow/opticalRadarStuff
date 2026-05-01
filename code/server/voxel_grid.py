"""
voxel_grid.py
PURPOSE: 3D grid for accumulating ray intersections.
"""

import numpy as np
from typing import List, Tuple, Optional, Any
from dataclasses import dataclass

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
    resolution_m: float = 1.0  # Voxel size
    decay_rate: float = 0.95  # Per-frame decay
    hot_threshold: float = 5.0  # Minimum heat to consider "hot"


@dataclass
class HotVoxel:
    """A voxel above the heat threshold."""
    x: int
    y: int
    z: int
    heat: float
    center: np.ndarray  # Center position in world coords


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
        self.config = config or VoxelGridConfig()
        
        # Calculate grid dimensions
        self.nx = int(self.config.width_m / self.config.resolution_m)
        self.ny = int(self.config.depth_m / self.config.resolution_m)
        self.nz = int(self.config.height_m / self.config.resolution_m)
        
        # Grid origin (center of grid at ground level)
        self.origin = np.array([
            -self.config.width_m / 2,
            -self.config.depth_m / 2,
            0.0
        ])
        
        # Allocate grid
        self.grid = np.zeros((self.nx, self.ny, self.nz), dtype=np.float32)
    
    def reset(self) -> None:
        """Clear all heat values."""
        self.grid.fill(0)
    
    def decay(self) -> None:
        """Apply decay to all voxels."""
        self.grid *= self.config.decay_rate
    
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
    
    def add_ray(
        self,
        origin: np.ndarray,
        direction: np.ndarray,
        intensity: float = 1.0,
        max_distance: float = 150.0,
        step_size: float = 0.5
    ) -> int:
        """
        Add heat along a ray.
        
        Uses native C++ acceleration when available, otherwise falls
        back to pure Python (slower but functional).
        
        Args:
            origin: Ray origin [x, y, z]
            direction: Ray direction (unit vector)
            intensity: Heat to add per voxel
            max_distance: Maximum ray distance
            step_size: March step size
        
        Returns:
            Number of voxels updated
        """
        # Use native module if available (10-100x faster)
        if _NATIVE_MODULE is not None:
            return _NATIVE_MODULE.add_ray_to_grid(
                self.grid,
                origin,
                direction,
                intensity,
                step_size,
                max_distance,
                self.config.resolution_m,
                self.origin
            )
        
        # Python fallback
        direction = direction / np.linalg.norm(direction)
        
        updated = 0
        t = 0.0
        
        while t < max_distance:
            pos = origin + t * direction
            ix, iy, iz = self.world_to_grid(pos)
            
            if self.is_valid_index(ix, iy, iz):
                self.grid[ix, iy, iz] += intensity
                updated += 1
            
            t += step_size
        
        return updated
    
    def add_rays_batch(
        self,
        rays: List[Any],  # List of Ray objects
        max_distance: float = 150.0,
        step_size: float = 0.5
    ) -> int:
        """
        Add multiple rays efficiently.
        
        Uses native C++ batch processing when available for maximum performance.
        
        Args:
            rays: List of Ray objects containing origin, direction, and intensity
            max_distance: Maximum ray distance
        
        Returns:
            Total voxels updated
        """
        if not rays:
            return 0
        
        # Use native batch processing if available
        if _NATIVE_MODULE is not None:
            origins = np.array([r.origin for r in rays], dtype=np.float32)
            directions = np.array([r.direction for r in rays], dtype=np.float32)
            intensities = np.array([r.intensity for r in rays], dtype=np.float32)
            
            return _NATIVE_MODULE.add_rays_batch(
                self.grid,
                origins,
                directions,
                intensities,
                step_size,
                max_distance,
                self.config.resolution_m,
                self.origin
            )
        
        # Python fallback
        total = 0
        for r in rays:
            total += self.add_ray(r.origin, r.direction, r.intensity, max_distance, step_size)
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
        threshold = threshold or self.config.hot_threshold
        
        # Find hot indices
        hot_indices = np.argwhere(self.grid >= threshold)
        
        results = []
        for ix, iy, iz in hot_indices:
            results.append(HotVoxel(
                x=ix,
                y=iy,
                z=iz,
                heat=float(self.grid[ix, iy, iz]),
                center=self.grid_to_world(ix, iy, iz)
            ))
        
        # Sort by heat (descending)
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
            'dimensions': (self.nx, self.ny, self.nz),
            'total_voxels': self.nx * self.ny * self.nz,
            'max_heat': float(self.grid.max()),
            'mean_heat': float(self.grid.mean()),
            'hot_count': int((self.grid >= self.config.hot_threshold).sum())
        }
