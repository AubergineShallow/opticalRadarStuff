

"""
esp32_stub.py
PURPOSE: Python stub for ESP32 communication and coordination.

NOTE: The actual ESP32 runs C/C++ code with Arduino framework.
This stub is for simulation and server-side coordination.
"""

import time
import socket
import struct
from typing import Optional
from dataclasses import dataclass


@dataclass
class ESP32Config:
    """ESP32 node configuration."""
    node_id: str
    server_address: str
    server_port: int
    frame_rate: int = 15
    min_pixels: int = 50
    # Static pose for the simulated node (a real ESP32 gets this from GNSS).
    # Defaults sit next to the SF ENU reference origin so rays land in-grid.
    latitude: float = 37.7749
    longitude: float = -122.4194
    altitude: float = 10.0
    orientation: Tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)


@dataclass
class ESP32Frame:
    """Frame data from ESP32."""
    node_id: str
    timestamp: float
    sequence: int
    azimuth: float
    elevation: float
    intensity: int
    health: int


class ESP32Stub:
    """
    Python stub for ESP32 node.
    
    This simulates the ESP32's behavior for testing
    and provides utilities for parsing ESP32 packets.
    
    Real ESP32 code would be in C++ (see pseudocode/esp32/esp32_main.txt)
    """
    
    # LEGACY packet format (kept only for parse_packet compatibility with old
    # captures). No server component ever parsed this on the wire; the stub
    # now transmits real V3 TelemetryPackets (common.protocol) instead.
    #   version(1) + node_id(2) + timestamp(4) + sequence(4) +
    #   azimuth(2) + elevation(2) + intensity(1) + health(1) = 17 bytes
    PACKET_FORMAT = "<BHIIhhBB"
    PACKET_SIZE = 17
    
    def __init__(self, config: ESP32Config):
        """
        Initialize ESP32 stub.
        
        Args:
            config: Node configuration
        """
        self.config = config
        self._socket: Optional[socket.socket] = None
        self._sequence = 0
        self._running = False
    
    def start(self) -> bool:
        """Start the stub node."""
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._running = True
            return True
        except Exception as e:
            print(f"ESP32 stub start failed: {e}")
            return False
    
    def stop(self) -> None:
        """Stop the stub node."""
        self._running = False
        if self._socket:
            self._socket.close()
            self._socket = None
    
    def send_detection(
        self,
        azimuth: float,
        elevation: float,
        intensity: int,
        health: int = 0x07
    ) -> bool:
        """
        Send a detection to the server as a V3 TelemetryPacket.

        The old 17-byte custom format was never parsed by any server
        component — every stub detection was silently dropped on arrival.

        Args:
            azimuth: Detection azimuth (degrees)
            elevation: Detection elevation (degrees)
            intensity: Detection intensity (0-255)
            health: Health flags

        Returns:
            True if sent
        """
        if not self._socket:
            return False

        from common.protocol import TelemetryPacket, MotionVector

        packet = TelemetryPacket(
            camera_id=self.config.node_id,
            sequence_number=self._sequence,
            timestamp=time.time(),
            latitude=self.config.latitude,
            longitude=self.config.longitude,
            altitude=self.config.altitude,
            orientation=self.config.orientation,
            health_flags=health,
            vectors=[MotionVector(
                azimuth=azimuth % 360.0,
                elevation=elevation,
                intensity=intensity,
                class_id=0,
            )],
        )

        self._sequence = (self._sequence + 1) & 0xFFFFFFFF

        try:
            self._socket.sendto(
                packet.pack(),
                (self.config.server_address, self.config.server_port)
            )
            return True
        except Exception:
            return False
    
    @staticmethod
    def parse_packet(data: bytes) -> Optional[ESP32Frame]:
        """
        Parse an ESP32 packet.
        
        Args:
            data: Raw packet bytes
        
        Returns:
            ESP32Frame or None
        """
        if len(data) < ESP32Stub.PACKET_SIZE:
            return None
        
        try:
            (version, node_id, timestamp, sequence,
             az_scaled, el_scaled, intensity, health) = struct.unpack(
                ESP32Stub.PACKET_FORMAT,
                data[:ESP32Stub.PACKET_SIZE]
            )
            
            # Unscale angles
            azimuth = (az_scaled / 32767) * 360
            elevation = el_scaled / 100.0
            
            return ESP32Frame(
                node_id=f"esp{node_id:02d}",
                timestamp=float(timestamp),
                sequence=sequence,
                azimuth=azimuth,
                elevation=elevation,
                intensity=intensity,
                health=health
            )
        except Exception:
            return None


def main():
    """Run the ESP32 stub as a standalone node."""
    import argparse
    from common.constants import UDP_PORT
    from common.protocol import AnnouncePacket
    
    parser = argparse.ArgumentParser(description="ESP32 Stub Node")
    parser.add_argument("--id", "-i", default="esp01", help="Node ID")
    parser.add_argument("--server", "-s", default="127.0.0.1", help="Server address")
    parser.add_argument("--port", "-p", type=int, default=UDP_PORT, help="Server port")
    parser.add_argument("--spec-file", default=None,
                        help="Path to node optics spec JSON (default: config/node_specs.json)")

    args = parser.parse_args()
    
    config = ESP32Config(
        node_id=args.id,
        server_address=args.server,
        server_port=args.port,
        frame_rate=15
    )
    
    stub = ESP32Stub(config)
    print(f"Starting ESP32 Stub: {args.id}")
    
    if not stub.start():
        print("Failed to start stub")
        return
        
    print(f"Sending to {args.server}:{args.port}")

    # Optical spec is provisioned in config/node_specs.json (keyed by node id),
    # NOT hardcoded here: an ESP32-CAM cannot read its lens FOV back in software,
    # so it must be declared in a file. Falls back to the file's _default entry,
    # then a built-in default, if this node id is absent.
    from common.node_specs import load_node_spec
    spec = load_node_spec(config.node_id, args.spec_file)
    FOV_H = spec.fov_horizontal
    FOV_V = spec.fov_vertical
    RES_W = spec.resolution_width
    RES_H = spec.resolution_height
    print(f"Optics for {config.node_id}: {spec.sensor} "
          f"FOV {FOV_H:.1f}x{FOV_V:.1f} @ {RES_W}x{RES_H}")
    
    try:
        last_announce = 0.0
        while True:
            now = time.time()
            
            # Announce every 5 seconds
            if now - last_announce > 5.0:
                # Manually construct packet
                pkt = AnnouncePacket(
                    camera_id=config.node_id,
                    timestamp=now,
                    fov_horizontal=FOV_H,
                    fov_vertical=FOV_V,
                    resolution_width=RES_W,
                    resolution_height=RES_H,
                    fps=config.frame_rate
                )
                
                # We need to send this via the stub's socket
                if stub._socket:
                    try:
                        stub._socket.sendto(pkt.pack(), (config.server_address, config.server_port))
                        print(f"Sent ANNOUNCE from {args.id}")
                    except Exception as e:
                        print(f"Announce error: {e}")
                
                last_announce = now
            
            # Simulate detection
            # 30% chance of detection
            if int(now * 10) % 10 < 3:
                az = (now * 20) % 360  # Rotating signal
                el = 10.0
                intensity = 200
                stub.send_detection(az, el, intensity)
            
            time.sleep(1.0 / config.frame_rate)
            
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        stub.stop()


if __name__ == "__main__":
    main()
