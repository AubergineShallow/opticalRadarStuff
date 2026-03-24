"""
tracker.py
PURPOSE: Main tracking interface combining all components (2D fork).
"""

import time
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from .kalman_filter import KalmanFilter
from .data_association import associate
from .track_manager import TrackManager, Track, TrackState


@dataclass
class Detection:
    """Single detection from grid (2D)."""
    position: np.ndarray  # [x, y] in EN
    confidence: float = 1.0
    class_id: int = 0
    timestamp: float = 0.0


@dataclass
class TrackingResult:
    """Result of tracking step."""
    tracks: List[Track]
    new_tracks: List[int]
    updated_tracks: List[int]
    lost_tracks: List[int]
    deleted_tracks: List[int]


class Tracker:
    """
    Main object tracker (2D fork).

    Combines:
        - Kalman filter for 2D state estimation
        - Hungarian algorithm for data association
        - Track manager for lifecycle

    Usage:
        tracker = Tracker()
        while running:
            detections = get_detections()
            result = tracker.update(detections)
            confirmed_tracks = tracker.get_confirmed_tracks()
    """

    def __init__(
        self,
        distance_threshold: float = 5.0,
        min_hits_to_confirm: int = 3,
        max_misses_to_delete: int = 30,
        max_tracks: int = 100,
        q_process_noise: float = 0.1,
        r_measurement_noise: float = 2.0,
        room_bounds: tuple = None,
        boundary_margin: float = 0.5
    ):
        self.distance_threshold = distance_threshold
        self.room_bounds = room_bounds  # (half_width, half_depth) in meters
        self.boundary_margin = boundary_margin

        self._track_manager = TrackManager(
            min_hits_to_confirm=min_hits_to_confirm,
            max_misses_to_delete=max_misses_to_delete,
            max_tracks=max_tracks,
            q_process_noise=q_process_noise,
            r_measurement_noise=r_measurement_noise,
            room_bounds=room_bounds
        )

        self._last_update_time: Optional[float] = None

    def update(
        self,
        detections: List[Detection],
        timestamp: Optional[float] = None
    ) -> TrackingResult:
        """
        Process new frame of detections.

        Args:
            detections: List of detections (2D positions)
            timestamp: Frame timestamp (default: current time)

        Returns:
            Tracking result with update info
        """
        timestamp = timestamp or time.time()

        if self._last_update_time is None:
            dt = 0.033
        else:
            dt = timestamp - self._last_update_time
        self._last_update_time = timestamp

        active_tracks = self._track_manager.active_tracks

        predicted_positions = []
        track_ids = []
        for track in active_tracks:
            self._track_manager.predict_track(track.track_id, dt)
            predicted_positions.append(track.position)
            track_ids.append(track.track_id)

        measurements = [d.position for d in detections]

        # Layer 2: Prune tracks that escaped room bounds
        if self.room_bounds:
            self._prune_out_of_bounds(track_ids, predicted_positions)
            # Rebuild lists after pruning (some tracks may be deleted)
            active_tracks = self._track_manager.active_tracks
            predicted_positions = [t.position for t in active_tracks]
            track_ids = [t.track_id for t in active_tracks]

        matches, unmatched_tracks, unmatched_dets = associate(
            predicted_positions,
            measurements,
            max_distance=self.distance_threshold
        )

        new_tracks = []
        updated_tracks = []
        lost_tracks = []
        deleted_tracks = []

        for track_idx, det_idx in matches:
            track_id = track_ids[track_idx]
            det = detections[det_idx]

            self._track_manager.update_track(
                track_id,
                det.position,
                dt,
                class_id=det.class_id,
                confidence=det.confidence
            )
            updated_tracks.append(track_id)

        for track_idx in unmatched_tracks:
            track_id = track_ids[track_idx]
            track = self._track_manager.mark_missed(track_id)

            if track:
                if track.state == TrackState.LOST:
                    lost_tracks.append(track_id)
                elif track.state == TrackState.DELETED:
                    deleted_tracks.append(track_id)

        for det_idx in unmatched_dets:
            det = detections[det_idx]
            track = self._track_manager.create_track(
                det.position,
                class_id=det.class_id,
                confidence=det.confidence
            )
            new_tracks.append(track.track_id)

        self._track_manager.cleanup_deleted()

        return TrackingResult(
            tracks=self._track_manager.active_tracks,
            new_tracks=new_tracks,
            updated_tracks=updated_tracks,
            lost_tracks=lost_tracks,
            deleted_tracks=deleted_tracks
        )

    def get_confirmed_tracks(self) -> List[Track]:
        """Get all confirmed tracks."""
        return self._track_manager.confirmed_tracks

    def get_all_tracks(self) -> List[Track]:
        """Get all active tracks."""
        return self._track_manager.active_tracks

    def get_track(self, track_id: int) -> Optional[Track]:
        """Get specific track by ID."""
        return self._track_manager.get_track(track_id)

    def get_stats(self) -> Dict[str, int]:
        """Get tracking statistics."""
        return self._track_manager.get_stats()

    def reset(self) -> None:
        """Reset tracker state."""
        self._track_manager = TrackManager(
            min_hits_to_confirm=self._track_manager.min_hits,
            max_misses_to_delete=self._track_manager.max_misses,
            max_tracks=self._track_manager.max_tracks
        )
        self._last_update_time = None

    def predict_positions(self, dt: float) -> Dict[int, np.ndarray]:
        """
        Predict track positions at future time.

        Args:
            dt: Time ahead to predict

        Returns:
            Dict of track_id -> predicted position [x, y]
        """
        return self._track_manager.get_predicted_positions(dt)

    def _prune_out_of_bounds(
        self,
        track_ids: List[int],
        predicted_positions: List[np.ndarray]
    ) -> None:
        """
        Layer 2: Hard-delete tracks whose predicted position exceeds room bounds + margin.
        """
        hw, hd = self.room_bounds
        margin = self.boundary_margin
        for tid, pos in zip(track_ids, predicted_positions):
            x, y = float(pos[0]), float(pos[1])
            if x < -(hw + margin) or x > (hw + margin) or \
               y < -(hd + margin) or y > (hd + margin):
                self._track_manager.delete_track(tid)
