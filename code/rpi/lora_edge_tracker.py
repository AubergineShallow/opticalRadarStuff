

"""
lora_edge_tracker.py
PURPOSE: A lightweight edge-side tracker to filter out noise and group detections into
persistent tracks before transmitting them over low-bandwidth LoRaWAN.
"""

import time
import math
from typing import List, Dict

class LocalTrack:
    def __init__(self, track_id: int, az: float, el: float, angular_size: float = 0.0):
        self.track_id = track_id
        self.az = az
        self.el = el
        # Apparent size travels in the LoRa UPDATE payload; without this field
        # lora_node's getattr(track, 'angular_size', 0.0) always sent 0.
        self.angular_size = angular_size
        self.hits = 1
        self.last_seen = time.time()
        self.active = False # Becomes active after N hits

class EdgeTracker:
    def __init__(self, required_hits: int = 10, max_missed_sec: float = 2.0):
        self.tracks: Dict[int, LocalTrack] = {}
        self.next_id = 1
        self.required_hits = required_hits
        self.max_missed_sec = max_missed_sec

    def update(self, detections: List[tuple]) -> List[LocalTrack]:
        """
        Match raw detections (az, el[, angular_size]) to existing tracks.
        Returns a list of mature, active tracks to broadcast.
        """
        now = time.time()

        # Simple nearest-neighbor association
        unmatched_detections = []

        for det in detections:
            det_az, det_el = det[0], det[1]
            det_size = det[2] if len(det) > 2 else 0.0
            best_dist = 5.0 # Max degrees to associate
            best_track = None

            for t_id, track in self.tracks.items():
                # Angular distance
                d_az = abs(track.az - det_az)
                if d_az > 180: d_az = 360 - d_az
                d_el = abs(track.el - det_el)
                dist = math.sqrt(d_az**2 + d_el**2)

                if dist < best_dist:
                    best_dist = dist
                    best_track = track

            if best_track:
                # Update track
                best_track.az = det_az
                best_track.el = det_el
                best_track.angular_size = det_size
                best_track.hits += 1
                best_track.last_seen = now
                if best_track.hits >= self.required_hits:
                    best_track.active = True
            else:
                unmatched_detections.append((det_az, det_el, det_size))

        # Create new tracks
        for az, el, size in unmatched_detections:
            track_id = self._allocate_id()
            if track_id is None:
                break  # all 250 ids alive; drop new detections rather than clobber
            self.tracks[track_id] = LocalTrack(track_id, az, el, size)

        # Cleanup stale tracks
        stale_ids = [t_id for t_id, t in self.tracks.items() if now - t.last_seen > self.max_missed_sec]
        for t_id in stale_ids:
            del self.tracks[t_id]

        # Return only mature, active tracks
        return [t for t in self.tracks.values() if t.active]

    def _allocate_id(self):
        """Next free id in [1, 250] (8-bit wire limit), or None if all live.

        The old bare wraparound handed out ids still held by live tracks,
        silently overwriting them in the dict after 250 creations.
        """
        for _ in range(250):
            candidate = self.next_id
            self.next_id = (self.next_id % 250) + 1
            if candidate not in self.tracks:
                return candidate
        return None
