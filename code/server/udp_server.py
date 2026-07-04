"""
udp_server.py
PURPOSE: Receive and process UDP telemetry packets.
"""

import socket
import time
import threading
from typing import Callable, Optional, List
from dataclasses import dataclass
from queue import Queue, Empty

import sys
import os
_parent = os.path.dirname(os.path.dirname(__file__))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from common.protocol import TelemetryPacket, HEADER_SIZE, SIGNATURE_SIZE, PACKET_TYPE_ANNOUNCE, AnnouncePacket
from common.constants import UDP_PORT, MAX_PACKET_SIZE


@dataclass
class ReceivedPacket:
    """Received packet with metadata."""
    packet: object  # TelemetryPacket or AnnouncePacket
    sender_ip: str
    sender_port: int
    receive_time: float


class UDPServer:
    """
    UDP server for receiving telemetry packets.

    Features:
        - Non-blocking packet reception
        - Packet queuing for processing

    Authentication happens at the object level in server_main._process_packet
    (single per-node KeyManager path). The transport-level authenticator this
    class used to accept was a second, divergent verification path that
    server_main never used — it mis-sized the header check and could not
    verify announce packets at all — so it was removed rather than left to
    drift.
    """

    def __init__(
        self,
        port: int = UDP_PORT,
        max_packet_size: int = MAX_PACKET_SIZE,
        buffer_size: int = 1000
    ):
        """
        Initialize UDP server.

        Args:
            port: UDP port to listen on
            max_packet_size: Maximum packet size
            buffer_size: Packet queue buffer size
        """
        self.port = port
        self.max_packet_size = max_packet_size
        
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        self._packet_queue: Queue = Queue(maxsize=buffer_size)
        
        # Stats
        self._packets_received = 0
        self._packets_dropped = 0
        self._auth_failures = 0
    
    def start(self) -> None:
        """Start the UDP server."""
        if self._running:
            return
        
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("0.0.0.0", self.port))
        self._socket.settimeout(0.1)
        
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """Stop the UDP server."""
        self._running = False
        
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        
        if self._socket:
            self._socket.close()
            self._socket = None
    
    def _receive_loop(self) -> None:
        """Main receive loop (runs in thread)."""
        while self._running:
            try:
                data, addr = self._socket.recvfrom(self.max_packet_size)
                receive_time = time.time()
                
                self._packets_received += 1
                
                # Process packet
                packet = self._process_packet(data, addr, receive_time)
                
                if packet:
                    try:
                        self._packet_queue.put_nowait(packet)
                    except Exception:
                        self._packets_dropped += 1
                        
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    print(f"UDP receive error: {e}")
    
    def _process_packet(
        self,
        data: bytes,
        addr: tuple,
        receive_time: float
    ) -> Optional[ReceivedPacket]:
        """Process received packet data (parse only; auth is object-level)."""
        sender_ip, sender_port = addr

        try:
            # Peek at packet type (Byte 1)
            # Header starts with Version (B) + Type (B)
            if len(data) >= 2:
                pkt_type = data[1]
                if pkt_type == PACKET_TYPE_ANNOUNCE:
                    packet = AnnouncePacket.unpack(data)
                else:
                    packet = TelemetryPacket.unpack(data)
            else:
                return None
        except Exception:
            return None

        return ReceivedPacket(
            packet=packet,
            sender_ip=sender_ip,
            sender_port=sender_port,
            receive_time=receive_time
        )
    
    def get_packet(self, timeout: float = 0.0) -> Optional[ReceivedPacket]:
        """
        Get next packet from queue.
        
        Args:
            timeout: Timeout in seconds (0 = non-blocking)
        
        Returns:
            ReceivedPacket or None
        """
        try:
            if timeout > 0:
                return self._packet_queue.get(timeout=timeout)
            else:
                return self._packet_queue.get_nowait()
        except Empty:
            return None
    
    def get_packets(self, max_count: int = 100) -> List[ReceivedPacket]:
        """
        Get multiple packets from queue.
        
        Args:
            max_count: Maximum packets to get
        
        Returns:
            List of packets
        """
        packets = []
        for _ in range(max_count):
            packet = self.get_packet()
            if packet is None:
                break
            packets.append(packet)
        return packets
    
    def send_command(
        self,
        data: bytes,
        address: str,
        port: int
    ) -> bool:
        """
        Send command packet to a camera.
        
        Args:
            data: Command packet bytes
            address: Camera IP address
            port: Camera port
        
        Returns:
            True if sent
        """
        if not self._socket:
            return False
        
        try:
            self._socket.sendto(data, (address, port))
            return True
        except Exception:
            return False
    
    def get_stats(self) -> dict:
        """Get server statistics."""
        return {
            'packets_received': self._packets_received,
            'packets_dropped': self._packets_dropped,
            'auth_failures': self._auth_failures,
            'queue_size': self._packet_queue.qsize(),
            'running': self._running
        }
    
    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running
