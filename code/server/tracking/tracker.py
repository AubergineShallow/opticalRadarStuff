"""
tracker.py
PURPOSE: Main tracking interface combining all components.
"""

import time
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from .data_association import associate
from .track_manager import TrackManager, Track, TrackState


@dataclass
class Detection:
    """Single detection from voxel grid."""
    position: np.ndarray  # [x, y, z] in ENU
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
    Main object tracker.
    
    Combines:
        - Kalman filter for state estimation
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
        r_measurement_noise: float = 2.0
    ):
        """
        Initialize tracker.
        
        Args:
            distance_threshold: Max distance for association
            min_hits_to_confirm: Hits to confirm track
            max_misses_to_delete: Misses before deletion
            max_tracks: Maximum tracks
            q_process_noise: Kalman process noise
            r_measurement_noise: Kalman measurement noise
        """
        self.distance_threshold = distance_threshold
        
        self._track_manager = TrackManager(
            min_hits_to_confirm=min_hits_to_confirm,
            max_misses_to_delete=max_misses_to_delete,
            max_tracks=max_tracks,
            q_process_noise=q_process_noise,
            r_measurement_noise=r_measurement_noise
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
            detections: List of detections
            timestamp: Frame timestamp (default: current time)
        
        Returns:
            Tracking result with update info
        """
        timestamp = timestamp or time.time()
        
        # Calculate dt
        if self._last_update_time is None:
            dt = 0.033  # Assume 30 fps initially
        else:
            dt = timestamp - self._last_update_time
        self._last_update_time = timestamp
        
        # Get current tracks
        active_tracks = self._track_manager.active_tracks
        
        # Predict all tracks forward
        predicted_positions = []
        track_ids = []
        for track in active_tracks:
            self._track_manager.predict_track(track.track_id, dt)
            predicted_positions.append(track.position)
            track_ids.append(track.track_id)
        
        # Get detection positions
        measurements = [d.position for d in detections]
        
        # Associate detections to tracks
        matches, unmatched_tracks, unmatched_dets = associate(
            predicted_positions,
            measurements,
            max_distance=self.distance_threshold
        )
        
        new_tracks = []
        updated_tracks = []
        lost_tracks = []
        deleted_tracks = []
        
        # Update matched tracks
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
        
        # Mark unmatched tracks as missed
        for track_idx in unmatched_tracks:
            track_id = track_ids[track_idx]
            track = self._track_manager.mark_missed(track_id)
            
            if track:
                if track.state == TrackState.LOST:
                    lost_tracks.append(track_id)
                elif track.state == TrackState.DELETED:
                    deleted_tracks.append(track_id)
        
        # Create new tracks for unmatched detections
        for det_idx in unmatched_dets:
            det = detections[det_idx]
            track = self._track_manager.create_track(
                det.position,
                class_id=det.class_id,
                confidence=det.confidence
            )
            new_tracks.append(track.track_id)
        
        # Cleanup deleted tracks
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
            Dict of track_id -> predicted position
        """
        return self._track_manager.get_predicted_positions(dt)
