
"""
visualizer.py
PURPOSE: 3D visualization of voxel grid and detections.
"""

import numpy as np
from typing import List, Optional, Tuple
from dataclasses import dataclass

try:
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


@dataclass
class VisualizerConfig:
    """Visualization configuration."""
    width: int = 800
    height: int = 600
    update_interval_ms: int = 100
    show_grid: bool = True
    show_cameras: bool = True
    show_rays: bool = False
    show_tracks: bool = True
    track_history_length: int = 50


class Visualizer:
    """
    3D visualization for the optical radar system.
    
    Shows:
        - Voxel grid heat map
        - Camera positions
        - Detection points
        - Track trajectories
    """
    
    def __init__(self, config: Optional[VisualizerConfig] = None):
        """
        Initialize visualizer.
        
        Args:
            config: Visualization config
        """
        self.config = config or VisualizerConfig()
        
        if not HAS_MATPLOTLIB:
            print("Warning: matplotlib not available, visualization disabled")
            self._enabled = False
            return
        
        self._enabled = True
        self._fig = None
        self._ax = None
        
        # Track history for trajectories
        self._track_history: dict = {}
    
    def setup(self) -> None:
        """Set up the visualization window."""
        if not self._enabled:
            return
        
        plt.ion()
        self._fig = plt.figure(figsize=(10, 8))
        self._ax = self._fig.add_subplot(111, projection='3d')
        
        self._ax.set_xlabel('East (m)')
        self._ax.set_ylabel('North (m)')
        self._ax.set_zlabel('Up (m)')
        self._ax.set_title('OpticalRadar 3D View')
    
    def update(
        self,
        detections: List[np.ndarray],
        camera_positions: Optional[List[Tuple[str, np.ndarray]]] = None,
        tracks: Optional[List[Tuple[int, np.ndarray]]] = None,
        hot_voxels: Optional[List[Tuple[np.ndarray, float]]] = None
    ) -> None:
        """
        Update visualization.
        
        Args:
            detections: List of detection positions
            camera_positions: List of (camera_id, position) tuples
            tracks: List of (track_id, position) tuples
            hot_voxels: List of (position, heat) tuples
        """
        if not self._enabled or self._ax is None:
            return
        
        self._ax.clear()
        
        # Draw hot voxels
        if hot_voxels and self.config.show_grid:
            positions = np.array([v[0] for v in hot_voxels])
            heats = np.array([v[1] for v in hot_voxels])
            
            if len(positions) > 0:
                # Normalize heat for color
                max_heat = max(heats.max(), 1)
                colors = plt.cm.hot(heats / max_heat)
                
                self._ax.scatter(
                    positions[:, 0], positions[:, 1], positions[:, 2],
                    c=colors, s=10, alpha=0.5, label='Voxels'
                )
        
        # Draw detections
        if detections:
            dets = np.array(detections)
            self._ax.scatter(
                dets[:, 0], dets[:, 1], dets[:, 2],
                c='blue', s=100, marker='o', label='Detections'
            )
        
        # Draw cameras
        if camera_positions and self.config.show_cameras:
            for cam_id, pos in camera_positions:
                self._ax.scatter(
                    pos[0], pos[1], pos[2],
                    c='green', s=200, marker='^'
                )
                self._ax.text(pos[0], pos[1], pos[2] + 2, cam_id)
        
        # Draw tracks with history
        if tracks and self.config.show_tracks:
            for track_id, pos in tracks:
                # Update history
                if track_id not in self._track_history:
                    self._track_history[track_id] = []
                
                self._track_history[track_id].append(pos.copy())
                
                # Limit history length
                max_len = self.config.track_history_length
                if len(self._track_history[track_id]) > max_len:
                    self._track_history[track_id] = self._track_history[track_id][-max_len:]
                
                # Draw trajectory
                history = np.array(self._track_history[track_id])
                if len(history) > 1:
                    self._ax.plot(
                        history[:, 0], history[:, 1], history[:, 2],
                        'r-', alpha=0.5, linewidth=1
                    )
                
                # Draw current position
                self._ax.scatter(
                    pos[0], pos[1], pos[2],
                    c='red', s=150, marker='*'
                )
                self._ax.text(pos[0], pos[1], pos[2] + 3, f'T{track_id}')
        
        # Set labels
        self._ax.set_xlabel('East (m)')
        self._ax.set_ylabel('North (m)')
        self._ax.set_zlabel('Up (m)')
        
        # Set equal aspect ratio
        self._set_axes_equal()
        
        # Refresh
        self._fig.canvas.draw()
        self._fig.canvas.flush_events()
    
    def _set_axes_equal(self) -> None:
        """Make axes equal scale."""
        if self._ax is None:
            return
        
        limits = np.array([
            self._ax.get_xlim3d(),
            self._ax.get_ylim3d(),
            self._ax.get_zlim3d()
        ])
        
        center = np.mean(limits, axis=1)
        radius = 0.5 * np.max(np.abs(limits[:, 1] - limits[:, 0]))
        
        self._ax.set_xlim3d([center[0] - radius, center[0] + radius])
        self._ax.set_ylim3d([center[1] - radius, center[1] + radius])
        self._ax.set_zlim3d([center[2] - radius, center[2] + radius])
    
    def close(self) -> None:
        """Close visualization window."""
        if self._fig:
            plt.close(self._fig)
            self._fig = None
            self._ax = None
    
    def clear_track_history(self) -> None:
        """Clear track history."""
        self._track_history.clear()
    
    @property
    def is_enabled(self) -> bool:
        """Check if visualization is enabled."""
        return self._enabled
