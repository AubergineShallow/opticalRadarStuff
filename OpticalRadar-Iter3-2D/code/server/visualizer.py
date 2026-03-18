"""
visualizer.py
PURPOSE: 2D visualization of grid and detections (2D fork).
"""

import numpy as np
from typing import List, Optional, Tuple
from dataclasses import dataclass

try:
    import matplotlib.pyplot as plt
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
    2D visualization for the optical radar system (2D fork).

    Shows:
        - Grid heat map (top-down)
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
        self._fig, self._ax = plt.subplots(figsize=(10, 8))

        self._ax.set_xlabel('East (m)')
        self._ax.set_ylabel('North (m)')
        self._ax.set_title('OpticalRadar 2D View')
        self._ax.set_aspect('equal')
        self._ax.grid(True, alpha=0.3)

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
            detections: List of detection positions [x, y]
            camera_positions: List of (camera_id, position) tuples
            tracks: List of (track_id, position) tuples
            hot_voxels: List of (position, heat) tuples  (hot cells)
        """
        if not self._enabled or self._ax is None:
            return

        self._ax.clear()

        # Draw hot cells
        if hot_voxels and self.config.show_grid:
            positions = np.array([v[0][:2] for v in hot_voxels])
            heats = np.array([v[1] for v in hot_voxels])

            if len(positions) > 0:
                max_heat = max(heats.max(), 1)
                colors = plt.cm.hot(heats / max_heat)

                self._ax.scatter(
                    positions[:, 0], positions[:, 1],
                    c=colors, s=10, alpha=0.5, label='Cells'
                )

        # Draw detections
        if detections:
            dets = np.array([d[:2] for d in detections])
            self._ax.scatter(
                dets[:, 0], dets[:, 1],
                c='blue', s=100, marker='o', label='Detections'
            )

        # Draw cameras
        if camera_positions and self.config.show_cameras:
            for cam_id, pos in camera_positions:
                self._ax.scatter(
                    pos[0], pos[1],
                    c='green', s=200, marker='^'
                )
                self._ax.annotate(cam_id, (pos[0], pos[1]),
                                  textcoords="offset points",
                                  xytext=(5, 5))

        # Draw tracks with history
        if tracks and self.config.show_tracks:
            for track_id, pos in tracks:
                if track_id not in self._track_history:
                    self._track_history[track_id] = []

                self._track_history[track_id].append(pos[:2].copy())

                max_len = self.config.track_history_length
                if len(self._track_history[track_id]) > max_len:
                    self._track_history[track_id] = self._track_history[track_id][-max_len:]

                history = np.array(self._track_history[track_id])
                if len(history) > 1:
                    self._ax.plot(
                        history[:, 0], history[:, 1],
                        'r-', alpha=0.5, linewidth=1
                    )

                self._ax.scatter(
                    pos[0], pos[1],
                    c='red', s=150, marker='*'
                )
                self._ax.annotate(f'T{track_id}', (pos[0], pos[1]),
                                  textcoords="offset points",
                                  xytext=(5, 5))

        # Set labels
        self._ax.set_xlabel('East (m)')
        self._ax.set_ylabel('North (m)')
        self._ax.set_title('OpticalRadar 2D View')
        self._ax.set_aspect('equal')
        self._ax.grid(True, alpha=0.3)

        if detections or (tracks and tracks):
            self._ax.legend(loc='upper right')

        # Refresh
        self._fig.canvas.draw()
        self._fig.canvas.flush_events()

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
