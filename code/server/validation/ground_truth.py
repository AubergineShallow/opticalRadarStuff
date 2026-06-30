
"""
ground_truth.py
PURPOSE: Compare system detections against known reference positions.
"""

import time
import math
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict


class GroundTruthSource(Enum):
    """Source of ground truth data."""
    SIMULATION = "simulation"
    LANDMARK = "landmark"
    ADSB = "adsb"
    RADAR = "radar"
    MANUAL = "manual"


@dataclass
class GroundTruthEntry:
    """Single ground truth position."""
    object_id: str
    position: np.ndarray  # [x, y, z] ENU
    timestamp: float
    source: GroundTruthSource
    confidence: float = 1.0
    velocity: Optional[np.ndarray] = None


@dataclass
class DetectionComparison:
    """Comparison between detection and ground truth."""
    detection_pos: np.ndarray
    truth_pos: np.ndarray
    error: float
    object_id: str
    timestamp: float


@dataclass
class ValidationStats:
    """Aggregate validation statistics."""
    mean_error: float = 0.0
    std_error: float = 0.0
    min_error: float = 0.0
    max_error: float = 0.0
    match_rate: float = 0.0
    false_positive_rate: float = 0.0
    count: int = 0
    
    p50_error: float = 0.0
    p95_error: float = 0.0
    p99_error: float = 0.0


class GroundTruthValidator:
    """
    Validate detections against ground truth.
    
    Sources:
        - Simulation (exact positions)
        - Fixed landmarks
        - External feeds (ADS-B, radar)
    """
    
    def __init__(
        self,
        match_distance_threshold: float = 20.0,
        time_tolerance: float = 0.5
    ):
        """
        Initialize validator.
        
        Args:
            match_distance_threshold: Max distance for matching
            time_tolerance: Max time difference for matching
        """
        self.match_threshold = match_distance_threshold
        self.time_tolerance = time_tolerance
        
        # Ground truth storage (by timestamp bucket)
        self._entries: Dict[str, List[GroundTruthEntry]] = defaultdict(list)
        
        # Landmarks (static references)
        self._landmarks: Dict[str, GroundTruthEntry] = {}
        
        # Comparison history
        self._comparisons: List[DetectionComparison] = []
        self._max_history = 10000
    
    def add_ground_truth(
        self,
        object_id: str,
        position: np.ndarray,
        timestamp: float,
        source: GroundTruthSource = GroundTruthSource.SIMULATION,
        confidence: float = 1.0,
        velocity: Optional[np.ndarray] = None
    ) -> None:
        """
        Add ground truth entry.
        
        Args:
            object_id: Object identifier
            position: Position [x, y, z] in ENU
            timestamp: Unix timestamp
            source: Data source
            confidence: Confidence level (0-1)
            velocity: Optional velocity [vx, vy, vz]
        """
        entry = GroundTruthEntry(
            object_id=object_id,
            position=np.array(position),
            timestamp=timestamp,
            source=source,
            confidence=confidence,
            velocity=np.array(velocity) if velocity is not None else None
        )
        
        self._entries[object_id].append(entry)
        
        # Limit history per object
        if len(self._entries[object_id]) > 1000:
            self._entries[object_id] = self._entries[object_id][-1000:]
    
    def register_landmark(
        self,
        name: str,
        position: np.ndarray,
        description: str = ""
    ) -> None:
        """
        Register a fixed landmark.
        
        Args:
            name: Landmark name
            position: Position [x, y, z] in ENU
            description: Optional description
        """
        self._landmarks[name] = GroundTruthEntry(
            object_id=name,
            position=np.array(position),
            timestamp=0.0,  # Static
            source=GroundTruthSource.LANDMARK,
            confidence=1.0
        )
    
    def get_truth_at_time(
        self,
        timestamp: float,
        tolerance: Optional[float] = None
    ) -> List[GroundTruthEntry]:
        """
        Get ground truth positions near a timestamp.
        
        Args:
            timestamp: Query timestamp
            tolerance: Time tolerance (default: self.time_tolerance)
        
        Returns:
            List of ground truth entries
        """
        tolerance = tolerance or self.time_tolerance
        results = []
        
        # Check dynamic entries
        for object_id, entries in self._entries.items():
            # Find closest in time
            best = None
            best_dt = float('inf')
            
            for entry in entries:
                dt = abs(entry.timestamp - timestamp)
                if dt < tolerance and dt < best_dt:
                    best = entry
                    best_dt = dt
            
            if best:
                results.append(best)
        
        # Always include landmarks
        results.extend(self._landmarks.values())
        
        return results
    
    def compare_detection(
        self,
        detected_position: np.ndarray,
        timestamp: float
    ) -> Tuple[Optional[GroundTruthEntry], float]:
        """
        Compare detection to ground truth.
        
        Args:
            detected_position: Detected position [x, y, z]
            timestamp: Detection timestamp
        
        Returns:
            Tuple of (matched truth entry, error distance)
        """
        truths = self.get_truth_at_time(timestamp)
        
        if not truths:
            return None, float('inf')
        
        best_truth = None
        best_error = float('inf')
        
        for truth in truths:
            error = float(np.linalg.norm(detected_position - truth.position))
            if error < best_error:
                best_truth = truth
                best_error = error
        
        # Record comparison
        if best_truth and best_error <= self.match_threshold:
            self._comparisons.append(DetectionComparison(
                detection_pos=np.array(detected_position),
                truth_pos=best_truth.position,
                error=best_error,
                object_id=best_truth.object_id,
                timestamp=timestamp
            ))
            
            # Limit history
            if len(self._comparisons) > self._max_history:
                self._comparisons = self._comparisons[-self._max_history:]
        
        return best_truth, best_error
    
    def batch_evaluate(
        self,
        detections: List[Tuple[np.ndarray, float]],  # (position, timestamp)
        ground_truths: Optional[List[GroundTruthEntry]] = None
    ) -> ValidationStats:
        """
        Evaluate batch of detections.
        
        Args:
            detections: List of (position, timestamp) tuples
            ground_truths: Optional explicit truth list
        
        Returns:
            Validation statistics
        """
        if ground_truths:
            # Add provided ground truths
            for entry in ground_truths:
                self.add_ground_truth(
                    entry.object_id,
                    entry.position,
                    entry.timestamp,
                    entry.source,
                    entry.confidence
                )
        
        errors = []
        matched = 0
        unmatched_dets = 0
        
        for pos, ts in detections:
            truth, error = self.compare_detection(pos, ts)
            
            if truth and error <= self.match_threshold:
                errors.append(error)
                matched += 1
            else:
                unmatched_dets += 1
        
        if not errors:
            return ValidationStats()
        
        errors = np.array(sorted(errors))
        n = len(errors)
        
        return ValidationStats(
            mean_error=float(np.mean(errors)),
            std_error=float(np.std(errors)),
            min_error=float(errors[0]),
            max_error=float(errors[-1]),
            match_rate=matched / len(detections) if detections else 0,
            false_positive_rate=unmatched_dets / len(detections) if detections else 0,
            count=n,
            p50_error=float(errors[n // 2]),
            p95_error=float(errors[int(n * 0.95)]) if n >= 20 else float(errors[-1]),
            p99_error=float(errors[int(n * 0.99)]) if n >= 100 else float(errors[-1])
        )
    
    def get_recent_stats(self, window_seconds: float = 60.0) -> ValidationStats:
        """Get statistics for recent comparisons."""
        now = time.time()
        cutoff = now - window_seconds
        
        recent = [c for c in self._comparisons if c.timestamp > cutoff]
        
        if not recent:
            return ValidationStats()
        
        errors = np.array(sorted([c.error for c in recent]))
        n = len(errors)
        
        return ValidationStats(
            mean_error=float(np.mean(errors)),
            std_error=float(np.std(errors)),
            min_error=float(errors[0]),
            max_error=float(errors[-1]),
            count=n,
            p50_error=float(errors[n // 2]),
            p95_error=float(errors[int(n * 0.95)]) if n >= 20 else float(errors[-1]),
            p99_error=float(errors[int(n * 0.99)]) if n >= 100 else float(errors[-1])
        )
    
    def generate_report(self, since: Optional[float] = None) -> str:
        """Generate accuracy report."""
        since = since or (time.time() - 1800)  # Last 30 min
        
        recent = [c for c in self._comparisons if c.timestamp > since]
        
        if not recent:
            return "No ground truth comparisons available."
        
        stats = self.get_recent_stats()
        
        # Rating
        if stats.mean_error < 2:
            rating = "EXCELLENT"
        elif stats.mean_error < 5:
            rating = "GOOD"
        elif stats.mean_error < 10:
            rating = "ACCEPTABLE"
        else:
            rating = "POOR"
        
        # Group by object
        by_object: Dict[str, List[float]] = defaultdict(list)
        for c in recent:
            by_object[c.object_id].append(c.error)
        
        lines = [
            "Ground Truth Validation Report",
            "=" * 40,
            "",
            f"Time Period: {time.strftime('%H:%M', time.localtime(since))} - now",
            f"Total Comparisons: {stats.count}",
            "",
            "POSITION ACCURACY:",
            f"- Mean Error: {stats.mean_error:.1f}m",
            f"- Std Dev: {stats.std_error:.1f}m",
            f"- 50th Percentile: {stats.p50_error:.1f}m",
            f"- 95th Percentile: {stats.p95_error:.1f}m",
            f"- 99th Percentile: {stats.p99_error:.1f}m",
            "",
            f"RATING: {rating}",
            "",
            "BY OBJECT:"
        ]
        
        for obj_id, errors in sorted(by_object.items()):
            mean_err = np.mean(errors)
            lines.append(f"- {obj_id}: {mean_err:.1f}m ({len(errors)} comparisons)")
        
        return '\n'.join(lines)
    
    def reset(self) -> None:
        """Clear all data."""
        self._entries.clear()
        self._comparisons.clear()
        # Keep landmarks
