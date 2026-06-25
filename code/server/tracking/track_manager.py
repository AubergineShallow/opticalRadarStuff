"""
track_manager.py
PURPOSE: Manage track lifecycle (creation, confirmation, deletion).
"""

import time
import numpy as np
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from enum import IntEnum

from .kalman_filter import KalmanFilter, KalmanState


class TrackState(IntEnum):
    """Track lifecycle states."""
    TENTATIVE = 0   # New track, not yet confirmed
    CONFIRMED = 1   # Confirmed track with sufficient hits
    LOST = 2        # Track lost detection, may recover
    DELETED = 3     # Track to be removed


@dataclass
class Track:
    """Single tracked object."""
    track_id: int
    state: TrackState
    kalman_state: KalmanState
    
    # Counters
    hits: int = 0
    misses: int = 0
    age: int = 0
    
    # Timestamps
    created_at: float = 0.0
    last_update: float = 0.0
    
    # Metadata
    class_id: int = 0
    confidence: float = 0.0
    
    @property
    def position(self) -> np.ndarray:
        """Get current position."""
        return self.kalman_state.position
    
    @property
    def velocity(self) -> np.ndarray:
        """Get current velocity."""
        return self.kalman_state.velocity
    
    @property
    def is_active(self) -> bool:
        """Check if track is still active."""
        return self.state in (TrackState.TENTATIVE, TrackState.CONFIRMED, TrackState.LOST)


class TrackManager:
    """
    Manage track lifecycle.
    
    Track lifecycle:
        1. TENTATIVE: New track from unmatched detection
        2. CONFIRMED: After min_hits consecutive matches
        3. LOST: After missing detections (can recover)
        4. DELETED: After max_misses, removed from system
    """
    
    def __init__(
        self,
        min_hits_to_confirm: int = 3,
        max_misses_to_delete: int = 30,
        max_tracks: int = 100,
        q_process_noise: float = 0.1,
        r_measurement_noise: float = 2.0
    ):
        """
        Initialize track manager.
        
        Args:
            min_hits_to_confirm: Hits needed to confirm track
            max_misses_to_delete: Misses before deletion
            max_tracks: Maximum number of tracks
            q_process_noise: Kalman filter process noise
            r_measurement_noise: Kalman filter measurement noise
        """
        self.min_hits = min_hits_to_confirm
        self.max_misses = max_misses_to_delete
        self.max_tracks = max_tracks
        
        self._tracks: Dict[int, Track] = {}
        self._next_id: int = 1
        
        self._kalman = KalmanFilter(
            q_process_noise=q_process_noise,
            r_measurement_noise=r_measurement_noise
        )
    
    @property
    def all_tracks(self) -> List[Track]:
        """Get all tracks."""
        return list(self._tracks.values())
    
    @property
    def active_tracks(self) -> List[Track]:
        """Get active (non-deleted) tracks."""
        return [t for t in self._tracks.values() if t.is_active]
    
    @property
    def confirmed_tracks(self) -> List[Track]:
        """Get confirmed tracks only."""
        return [t for t in self._tracks.values() 
                if t.state == TrackState.CONFIRMED]
    
    def get_track(self, track_id: int) -> Optional[Track]:
        """Get track by ID."""
        return self._tracks.get(track_id)
    
    def create_track(
        self,
        position: np.ndarray,
        class_id: int = 0,
        confidence: float = 1.0
    ) -> Track:
        """
        Create new tentative track.
        
        Args:
            position: Initial position [x, y, z]
            class_id: Object class
            confidence: Detection confidence
        
        Returns:
            New track
        """
        # Enforce max tracks
        if len(self._tracks) >= self.max_tracks:
            self._prune_oldest()
        
        now = time.time()
        
        track = Track(
            track_id=self._next_id,
            state=TrackState.TENTATIVE,
            kalman_state=self._kalman.initialize(position),
            hits=1,
            misses=0,
            age=1,
            created_at=now,
            last_update=now,
            class_id=class_id,
            confidence=confidence
        )
        
        self._tracks[self._next_id] = track
        self._next_id += 1
        
        return track
    
    def update_track(
        self,
        track_id: int,
        measurement: np.ndarray,
        dt: float,
        class_id: Optional[int] = None,
        confidence: Optional[float] = None
    ) -> Optional[Track]:
        """
        Update track with new detection.
        
        Args:
            track_id: Track ID
            measurement: Detection position [x, y, z]
            dt: Time since last update
            class_id: Optional class update
            confidence: Optional confidence update
        
        Returns:
            Updated track or None
        """
        track = self._tracks.get(track_id)
        if not track or track.state == TrackState.DELETED:
            return None
        
        # Kalman predict + update
        predicted = self._kalman.predict(track.kalman_state, dt)
        updated, _ = self._kalman.update(predicted, measurement)
        
        track.kalman_state = updated
        track.hits += 1
        track.misses = 0
        track.age += 1
        track.last_update = time.time()
        
        if class_id is not None:
            track.class_id = class_id
        if confidence is not None:
            track.confidence = confidence
        
        # State transitions
        if track.state == TrackState.TENTATIVE:
            if track.hits >= self.min_hits:
                track.state = TrackState.CONFIRMED
        elif track.state == TrackState.LOST:
            track.state = TrackState.CONFIRMED
        
        return track
    
    def predict_track(self, track_id: int, dt: float) -> Optional[Track]:
        """
        Predict track forward (no measurement).
        
        Args:
            track_id: Track ID
            dt: Time step
        
        Returns:
            Predicted track or None
        """
        track = self._tracks.get(track_id)
        if not track or track.state == TrackState.DELETED:
            return None
        
        track.kalman_state = self._kalman.predict(track.kalman_state, dt)
        track.age += 1
        
        return track
    
    def predict_all_active(self, dt: float) -> List[Track]:
        """
        Predict every active track forward by dt in one vectorized call.
        
        Equivalent to calling predict_track() on each active track, but
        avoids both the repeated dict lookups and, more importantly, the
        per-track reconstruction of the (shared, dt-only-dependent)
        Kalman F/Q matrices and small matmuls -- those get batched into
        one call via KalmanFilter.predict_batch() instead of running once
        per track, every frame, up to max_tracks times.
        
        Args:
            dt: Time step, shared across all active tracks this frame
        
        Returns:
            The active tracks (now predicted forward), same objects as
            self.active_tracks would return.
        """
        tracks = self.active_tracks
        if not tracks:
            return []
        
        predicted_states = self._kalman.predict_batch(
            [t.kalman_state for t in tracks], dt
        )
        
        for track, state in zip(tracks, predicted_states):
            track.kalman_state = state
            track.age += 1
        
        return tracks
    
    def mark_missed(self, track_id: int) -> Optional[Track]:
        """
        Mark track as missed (no detection this frame).
        
        Args:
            track_id: Track ID
        
        Returns:
            Updated track or None
        """
        track = self._tracks.get(track_id)
        if not track or track.state == TrackState.DELETED:
            return None
        
        track.misses += 1
        
        # State transitions
        if track.state == TrackState.CONFIRMED:
            if track.misses >= 5:  # Lost threshold
                track.state = TrackState.LOST
        
        if track.misses >= self.max_misses:
            track.state = TrackState.DELETED
        
        return track
    
    def delete_track(self, track_id: int) -> None:
        """Mark track for deletion."""
        track = self._tracks.get(track_id)
        if track:
            track.state = TrackState.DELETED
    
    def cleanup_deleted(self) -> int:
        """
        Remove deleted tracks from memory.
        
        Returns:
            Number of tracks removed
        """
        deleted_ids = [
            tid for tid, track in self._tracks.items()
            if track.state == TrackState.DELETED
        ]
        
        for tid in deleted_ids:
            del self._tracks[tid]
        
        return len(deleted_ids)
    
    def _prune_oldest(self) -> None:
        """Remove oldest tentative track to make room."""
        tentative = [t for t in self._tracks.values() 
                     if t.state == TrackState.TENTATIVE]
        
        if tentative:
            oldest = min(tentative, key=lambda t: t.created_at)
            del self._tracks[oldest.track_id]
    
    def get_predicted_positions(self, dt: float = 0.0) -> Dict[int, np.ndarray]:
        """
        Get predicted positions for all active tracks.
        
        Args:
            dt: Time to predict forward
        
        Returns:
            Dict of track_id -> predicted position
        """
        positions = {}
        for track in self.active_tracks:
            if dt > 0:
                pos = self._kalman.predict_position(track.kalman_state, dt)
            else:
                pos = track.position
            positions[track.track_id] = pos
        return positions
    
    def get_stats(self) -> Dict[str, int]:
        """Get tracking statistics."""
        states = {}
        for track in self._tracks.values():
            state_name = track.state.name
            states[state_name] = states.get(state_name, 0) + 1
        
        return {
            'total': len(self._tracks),
            'active': len(self.active_tracks),
            'confirmed': len(self.confirmed_tracks),
            **states
        }
