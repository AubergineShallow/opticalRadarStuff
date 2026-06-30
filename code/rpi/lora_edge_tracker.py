
"""
lora_edge_tracker.py
PURPOSE: A lightweight edge-side tracker to filter out noise and group detections into
persistent tracks before transmitting them over low-bandwidth LoRaWAN.
"""

import time
import math
from typing import List, Dict

class LocalTrack:
    def __init__(self, track_id: int, az: float, el: float):
        self.track_id = track_id
        self.az = az
        self.el = el
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
        Match raw detections (az, el) to existing tracks.
        Returns a list of mature, active tracks to broadcast.
        """
        now = time.time()

        # Simple nearest-neighbor association
        unmatched_detections = []

        for det_az, det_el in detections:
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
                best_track.hits += 1
                best_track.last_seen = now
                if best_track.hits >= self.required_hits:
                    best_track.active = True
            else:
                unmatched_detections.append((det_az, det_el))

        # Create new tracks
        for az, el in unmatched_detections:
            self.tracks[self.next_id] = LocalTrack(self.next_id, az, el)
            self.next_id = (self.next_id % 250) + 1 # Keep IDs inside 8-bit limit

        # Cleanup stale tracks
        stale_ids = [t_id for t_id, t in self.tracks.items() if now - t.last_seen > self.max_missed_sec]
        for t_id in stale_ids:
            del self.tracks[t_id]

        # Return only mature, active tracks
        return [t for t in self.tracks.values() if t.active]
