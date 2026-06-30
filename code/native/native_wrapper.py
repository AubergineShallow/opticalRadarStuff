"""
Native module wrapper with Python fallback.

This module attempts to load the C++ extension for high performance,
falling back to pure Python if not available.
"""

import numpy as np
from typing import List, Tuple, Optional

# Try to import native module
try:
    from . import optical_radar_native as _native
    NATIVE_AVAILABLE = True
except ImportError:
    NATIVE_AVAILABLE = False
    print("Native C++ module not available, using Python fallback")


def add_ray_to_grid(
    grid: np.ndarray,
    origin: np.ndarray,
    direction: np.ndarray,
    intensity: float,
    step_size: float = 0.5,
    max_distance: float = 150.0,
    resolution: float = 1.0,
    grid_origin: np.ndarray = None
) -> int:
    """
    Add heat along a ray through the voxel grid.
    
    Args:
        grid: 3D numpy array (modified in place)
        origin: Ray origin [x, y, z]
        direction: Ray direction (normalized or not)
        intensity: Heat intensity to add
        step_size: March step size
        max_distance: Maximum ray distance
        resolution: Voxel size
        grid_origin: Grid origin [x, y, z]
    
    Returns:
        Number of voxels updated
    """
    if grid_origin is None:
        grid_origin = np.zeros(3)
    
    if NATIVE_AVAILABLE:
        # BUG-003: the native kernel writes heat IN PLACE. `.astype()` always
        # copies, so the native writes would land in a throwaway copy and the
        # caller's grid would never change. `np.asarray(..., dtype=float32)` is
        # a no-op (returns the same object) when grid is already float32, which
        # it always is here, preserving the in-place contract.
        return _native.add_ray_to_grid(
            np.asarray(grid, dtype=np.float32),
            float(origin[0]), float(origin[1]), float(origin[2]),
            float(direction[0]), float(direction[1]), float(direction[2]),
            float(intensity),
            float(step_size), float(max_distance), float(resolution),
            float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2])
        )
    
    # Python fallback
    direction = direction / np.linalg.norm(direction)
    nx, ny, nz = grid.shape
    
    updated = 0
    t = 0.0
    
    while t < max_distance:
        pos = origin + t * direction
        
        ix = int((pos[0] - grid_origin[0]) / resolution)
        iy = int((pos[1] - grid_origin[1]) / resolution)
        iz = int((pos[2] - grid_origin[2]) / resolution)
        
        if 0 <= ix < nx and 0 <= iy < ny and 0 <= iz < nz:
            grid[ix, iy, iz] += intensity
            updated += 1
        
        t += step_size
    
    return updated


def add_rays_batch(
    grid: np.ndarray,
    origins: np.ndarray,
    directions: np.ndarray,
    intensities: np.ndarray,
    step_size: float = 0.5,
    max_distance: float = 150.0,
    resolution: float = 1.0,
    grid_origin: np.ndarray = None
) -> int:
    """
    Add multiple rays to the grid in batch.
    
    Args:
        grid: 3D numpy array (modified in place)
        origins: Ray origins (N, 3)
        directions: Ray directions (N, 3)
        intensities: Heat intensities (N,)
        step_size: March step size
        max_distance: Maximum ray distance
        resolution: Voxel size
        grid_origin: Grid origin [x, y, z]
    
    Returns:
        Total voxels updated
    """
    if grid_origin is None:
        grid_origin = np.zeros(3)
    
    if NATIVE_AVAILABLE:
        # BUG-003: grid is written in place — must not be copied (see add_ray_to_grid).
        # origins/directions/intensities are read-only inputs, so copying those is fine.
        return _native.add_rays_batch(
            np.asarray(grid, dtype=np.float32),
            origins.astype(np.float32),
            directions.astype(np.float32),
            intensities.astype(np.float32),
            float(step_size), float(max_distance), float(resolution),
            float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2])
        )
    
    # Python fallback
    total = 0
    for i in range(len(origins)):
        total += add_ray_to_grid(
            grid, origins[i], directions[i], intensities[i],
            step_size, max_distance, resolution, grid_origin
        )
    return total


def decay_grid(grid: np.ndarray, decay_rate: float) -> None:
    """
    Apply decay to entire grid (in place).
    
    Args:
        grid: 3D numpy array (modified in place)
        decay_rate: Decay factor (e.g., 0.95)
    """
    if NATIVE_AVAILABLE:
        # BUG-003: decay scales the grid in place — pass the real array, not a copy.
        _native.decay_grid(np.asarray(grid, dtype=np.float32), float(decay_rate))
    else:
        grid *= decay_rate


def find_hot_voxels(
    grid: np.ndarray,
    threshold: float,
    resolution: float = 1.0,
    grid_origin: np.ndarray = None
) -> np.ndarray:
    """
    Find voxels above heat threshold.
    
    Args:
        grid: 3D numpy array
        threshold: Heat threshold
        resolution: Voxel size
        grid_origin: Grid origin [x, y, z]
    
    Returns:
        Array of (N, 4) with [x, y, z, heat] for each hot voxel
    """
    if grid_origin is None:
        grid_origin = np.zeros(3)
    
    if NATIVE_AVAILABLE:
        return _native.find_hot_voxels(
            grid.astype(np.float32),
            float(threshold),
            float(resolution),
            float(grid_origin[0]), float(grid_origin[1]), float(grid_origin[2])
        )
    
    # Python fallback
    hot_indices = np.argwhere(grid >= threshold)
    
    if len(hot_indices) == 0:
        return np.zeros((0, 4), dtype=np.float32)
    
    result = np.zeros((len(hot_indices), 4), dtype=np.float32)
    
    for i, (ix, iy, iz) in enumerate(hot_indices):
        result[i, 0] = grid_origin[0] + (ix + 0.5) * resolution
        result[i, 1] = grid_origin[1] + (iy + 0.5) * resolution
        result[i, 2] = grid_origin[2] + (iz + 0.5) * resolution
        result[i, 3] = grid[ix, iy, iz]
    
    return result


def is_native_available() -> bool:
    """Check if native C++ module is available."""
    return NATIVE_AVAILABLE
