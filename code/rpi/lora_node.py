"""
lora_node.py
PURPOSE: The main runner for a Raspberry Pi utilizing a LoRaWAN hat.
"""

import time
import sys
import os

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.lora_protocol import LoraAnnouncePacket, LoraUpdatePacket
from rpi.lora_edge_tracker import EdgeTracker
from rpi.vision import VisionSystem, VisionConfig

class LoRaNode:
    def __init__(self, node_id: int):
        self.node_id = node_id

        # In a real scenario, these would come from GPS/IMU
        self.lat = 40.7128
        self.lon = -74.0060
        self.alt = 10.0
        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = 0.0

        self.vision = VisionSystem(VisionConfig(fps=10))
        self.tracker = EdgeTracker(required_hits=10, max_missed_sec=3.0)

        self.last_lora_tx = 0
        self.lora_duty_cycle_sec = 5.0 # Transmit at most once every 5 seconds

    def transmit_lora(self, data: bytes):
        """Mock hardware transmitter"""
        # Example: serial.write(data) to a LoRa HAT like the Dragino or RAK
        print(f"[LoRa TX] Sending {len(data)} bytes: {data.hex()}")

    def run(self):
        print(f"Starting LoRa Node {self.node_id}...")
        self.vision.start()

        # 1. Send Boot Announce
        announce = LoraAnnouncePacket(
            node_id=self.node_id,
            lat=self.lat, lon=self.lon, alt=self.alt,
            roll_deg=self.roll, pitch_deg=self.pitch, yaw_deg=self.yaw
        )
        self.transmit_lora(announce.pack())

        try:
            while True:
                # Get raw noisy vectors from OpenCV
                frame, vectors = self.vision.get_frame_and_vectors()

                if vectors:
                    raw_dets = [(v.azimuth, v.elevation) for v in vectors]

                    # Pass through edge tracker to filter noise
                    active_tracks = self.tracker.update(raw_dets)

                    now = time.time()
                    if active_tracks and (now - self.last_lora_tx) >= self.lora_duty_cycle_sec:
                        print(f"Found {len(active_tracks)} mature tracks. Transmitting via LoRa.")
                        for track in active_tracks:
                            update_pkt = LoraUpdatePacket(
                                node_id=self.node_id,
                                track_id=track.track_id,
                                azimuth=track.az,
                                elevation=track.el,
                                angular_size=getattr(track, 'angular_size', 0.0) # default to 0 if not tracked
                            )
                            self.transmit_lora(update_pkt.pack())
                            # Brief pause between track packets if required by hardware modem
                            time.sleep(0.1)

                        self.last_lora_tx = now
                else:
                    # Update tracker with empty to age out old tracks
                    self.tracker.update([])

                time.sleep(0.1) # Simulate 10 FPS

        except KeyboardInterrupt:
            print("Shutting down.")
            self.vision.stop()

if __name__ == "__main__":
    node = LoRaNode(node_id=5)
    node.run()
