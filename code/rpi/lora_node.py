

"""
lora_node.py
PURPOSE: Main runner for a Raspberry Pi edge node that reports over LoRa /
         Meshtastic instead of WiFi/UDP.

Vision -> edge tracker (maturation) -> compressed LoRa payloads
(common.lora_protocol) -> a common.lora_link transport.

Transports (choose with --transport):
  * meshtastic - hand payloads to a Meshtastic radio (USB/serial); the mesh
                 relays them to the server's Meshtastic node. Needs `meshtastic`.
  * serial     - a raw SX127x LoRa HAT / bridge exposed as a serial device.
                 Needs `pyserial`.
  * mock       - print the framed bytes (default; no hardware, no deps).
"""

import time
import sys
import os

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.lora_protocol import LoraAnnouncePacket, LoraUpdatePacket, frame_payload
from common.lora_link import make_transport, LoRaTransport
from rpi.lora_edge_tracker import EdgeTracker
from rpi.vision import VisionSystem, VisionConfig


class _MockTransport(LoRaTransport):
    """Prints framed payloads. Lets the node run end-to-end with no radio."""

    def start(self) -> bool:
        return True

    def send(self, payload: bytes) -> bool:
        framed = frame_payload(payload)
        print(f"[LoRa TX] {len(payload)}B payload "
              f"({len(framed)}B framed): {payload.hex()}")
        return True

    def poll(self):
        return []

    @property
    def is_running(self) -> bool:
        return True


class LoRaNode:
    def __init__(self, node_id: int, transport: LoRaTransport = None):
        self.node_id = node_id

        # TODO: source these live from rpi.gps / rpi.imu. Static for now.
        self.lat = 40.7128
        self.lon = -74.0060
        self.alt = 10.0
        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = 0.0

        self.vision = VisionSystem(VisionConfig(fps=10))
        self.tracker = EdgeTracker(required_hits=10, max_missed_sec=3.0)

        self.transport = transport or _MockTransport()

        self.last_lora_tx = 0.0
        self.last_announce = 0.0
        self.lora_duty_cycle_sec = 5.0   # Transmit at most once every 5 seconds
        self.announce_interval_sec = 5.0  # Re-announce pose periodically

    def transmit_lora(self, data: bytes) -> None:
        self.transport.send(data)

    def run(self):
        print(f"Starting LoRa Node {self.node_id} "
              f"({self.transport.__class__.__name__})...")
        self.transport.start()
        self.vision.start()

        try:
            while True:
                now = time.time()

                # Periodic pose announce (the server needs it to place rays).
                if now - self.last_announce >= self.announce_interval_sec:
                    announce = LoraAnnouncePacket(
                        node_id=self.node_id,
                        lat=self.lat, lon=self.lon, alt=self.alt,
                        roll_deg=self.roll, pitch_deg=self.pitch, yaw_deg=self.yaw,
                    )
                    self.transmit_lora(announce.pack())
                    self.last_announce = now

                # Get raw noisy vectors from OpenCV.
                frame, vectors = self.vision.get_frame_and_vectors()

                if vectors:
                    raw_dets = [(v.azimuth, v.elevation,
                                 getattr(v, 'angular_size', 0.0)) for v in vectors]
                    active_tracks = self.tracker.update(raw_dets)

                    if active_tracks and (now - self.last_lora_tx) >= self.lora_duty_cycle_sec:
                        print(f"Found {len(active_tracks)} mature tracks. Transmitting via LoRa.")
                        for track in active_tracks:
                            update_pkt = LoraUpdatePacket(
                                node_id=self.node_id,
                                track_id=track.track_id,
                                azimuth=track.az,
                                elevation=track.el,
                                angular_size=getattr(track, 'angular_size', 0.0),
                            )
                            self.transmit_lora(update_pkt.pack())
                            # Brief pause between frames if the modem needs it.
                            time.sleep(0.1)
                        self.last_lora_tx = now
                else:
                    # Age out old tracks even when nothing is seen.
                    self.tracker.update([])

                time.sleep(0.1)  # ~10 FPS

        except KeyboardInterrupt:
            print("Shutting down.")
        finally:
            self.vision.stop()
            self.transport.stop()


def _build_transport(args) -> LoRaTransport:
    if args.transport == "mock":
        return _MockTransport()
    if args.transport == "meshtastic":
        return make_transport("meshtastic", device=args.device or None)
    if args.transport == "serial":
        return make_transport("serial", port=args.device, baud=args.baud)
    raise SystemExit(f"Unknown transport: {args.transport}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LoRa / Meshtastic RPi edge node")
    parser.add_argument("--id", "-i", type=int, default=5, help="uint8 node id")
    parser.add_argument("--transport", "-t", default="mock",
                        choices=["mock", "meshtastic", "serial"])
    parser.add_argument("--device", "-d", default="",
                        help="serial device / meshtastic devPath")
    parser.add_argument("--baud", "-b", type=int, default=115200)
    args = parser.parse_args()

    node = LoRaNode(node_id=args.id, transport=_build_transport(args))
    node.run()


if __name__ == "__main__":
    main()
