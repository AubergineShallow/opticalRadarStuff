

"""
lora_gateway.py
PURPOSE: Server-side receiver ("gateway") for the compressed LoRa / Meshtastic
         payloads. This is the piece that lets a laptop-as-server ingest LoRa
         traffic: attach a Meshtastic radio over USB, point this gateway at it,
         and it feeds the SAME processing pipeline the UDP path uses.

It deliberately mirrors server.udp_server.UDPServer's public surface
(start / stop / get_packets / get_stats / is_running) and emits the exact same
ReceivedPacket objects, so server_main can drain it in the main loop with no
special-casing.

WHY IT IS STATEFUL
------------------
A LoRa UPDATE carries only a bearing (7 bytes); it has no room for the node's
pose. The pose arrives separately in the periodic ANNOUNCE. So the gateway
caches each node's most recent pose and, when an UPDATE arrives, synthesises a
full common.protocol.TelemetryPacket (pose + one MotionVector). An ANNOUNCE is
translated into a common.protocol.AnnouncePacket (optics from the node-spec
registry) so the server registers the node's optics and assigns it to a cluster,
exactly as a UDP node's announce would.
"""

import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import sys
import os
_parent = os.path.dirname(os.path.dirname(__file__))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from common.lora_protocol import (
    LoraAnnouncePacket, LoraUpdatePacket, unpack_lora,
    node_id_to_camera_id, DEFAULT_NODE_ID_PREFIX,
)
from common.lora_link import LoRaTransport
from common.protocol import (
    AnnouncePacket, TelemetryPacket, MotionVector,
    PACKET_TYPE_ANNOUNCE, PACKET_TYPE_TELEMETRY,
)
from common.node_specs import load_node_spec
from math_utils.quaternion import from_euler

# Nominal ray weight for a LoRa detection: the UPDATE payload spends no bytes on
# per-detection intensity, so every LoRa ray gets the same moderate weight.
LORA_DETECTION_INTENSITY = 200


@dataclass
class ReceivedPacket:
    """Mirror of server.udp_server.ReceivedPacket so the server loop is uniform."""
    packet: object
    sender_ip: str
    sender_port: int
    receive_time: float


@dataclass
class _NodePose:
    latitude: float
    longitude: float
    altitude: float
    orientation: tuple  # quaternion (w, x, y, z)


class LoRaGateway:
    """
    Ingest LoRa/Meshtastic payloads from a LoRaTransport and translate them into
    the server's native packet objects.

    Args:
        transport: a started-or-startable common.lora_link.LoRaTransport.
        node_id_prefix: string prefix used to build camera_ids (5 -> "lora05").
        specs_file: optional path to the node-spec JSON (optics per node id).
        poll_interval: reader-thread sleep between transport polls.
    """

    def __init__(
        self,
        transport: LoRaTransport,
        node_id_prefix: str = DEFAULT_NODE_ID_PREFIX,
        specs_file: Optional[str] = None,
        poll_interval: float = 0.05,
        logger=None,
    ):
        self.transport = transport
        self.node_id_prefix = node_id_prefix
        self.specs_file = specs_file
        self.poll_interval = poll_interval
        self._logger = logger

        self._poses: Dict[str, _NodePose] = {}
        self._sequence: Dict[str, int] = {}
        self._queue: List[ReceivedPacket] = []
        self._qlock = threading.Lock()

        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Stats (parallel to UDPServer.get_stats()).
        self._payloads_received = 0
        self._packets_emitted = 0
        self._decode_failures = 0
        self._orphan_updates = 0  # updates with no known pose yet
        self._queue_dropped = 0   # packets dropped because the queue was full

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self.transport.start()
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
        self._log("info", "LoRa gateway started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        try:
            self.transport.stop()
        except Exception:
            pass

    # -- reader thread -----------------------------------------------------
    def _receive_loop(self) -> None:
        while self._running:
            try:
                payloads = self.transport.poll()
                if payloads:
                    now = time.time()
                    for payload in payloads:
                        self._ingest(payload, now)
                else:
                    time.sleep(self.poll_interval)
            except Exception as e:
                if self._running:
                    self._log("error", f"LoRa gateway receive error: {e}")
                    time.sleep(self.poll_interval)

    def _ingest(self, payload: bytes, receive_time: float) -> None:
        self._payloads_received += 1
        decoded = unpack_lora(payload)
        if decoded is None:
            self._decode_failures += 1
            return

        if isinstance(decoded, LoraAnnouncePacket):
            rp = self._translate_announce(decoded, receive_time)
        elif isinstance(decoded, LoraUpdatePacket):
            rp = self._translate_update(decoded, receive_time)
        else:
            return

        if rp is not None:
            with self._qlock:
                # Bounded like UDPServer's queue (maxsize=1000): if the main
                # loop stalls, drop the newest instead of growing without limit.
                if len(self._queue) >= 1000:
                    self._queue_dropped += 1
                else:
                    self._queue.append(rp)
                    self._packets_emitted += 1

    # -- translation -------------------------------------------------------
    def _translate_announce(
        self, pkt: LoraAnnouncePacket, receive_time: float
    ) -> Optional[ReceivedPacket]:
        camera_id = node_id_to_camera_id(pkt.node_id, self.node_id_prefix)

        # Cache pose (Euler -> quaternion for the ray builder).
        self._poses[camera_id] = _NodePose(
            latitude=pkt.lat,
            longitude=pkt.lon,
            altitude=pkt.alt,
            orientation=from_euler(pkt.roll_deg, pkt.pitch_deg, pkt.yaw_deg),
        )

        # Optics come from the node-spec registry (the LoRa announce spends no
        # bytes on FOV/resolution). Falls back to the file's _default entry.
        spec = load_node_spec(camera_id, self.specs_file)
        announce = AnnouncePacket(
            camera_id=camera_id,
            timestamp=receive_time,
            fov_horizontal=spec.fov_horizontal,
            fov_vertical=spec.fov_vertical,
            resolution_width=spec.resolution_width,
            resolution_height=spec.resolution_height,
            fps=1,  # LoRa nodes report at most a few Hz; nominal.
        )
        return ReceivedPacket(announce, "lora", 0, receive_time)

    def _translate_update(
        self, pkt: LoraUpdatePacket, receive_time: float
    ) -> Optional[ReceivedPacket]:
        camera_id = node_id_to_camera_id(pkt.node_id, self.node_id_prefix)
        pose = self._poses.get(camera_id)
        if pose is None:
            # No pose yet: cannot place the ray. The node re-announces every few
            # seconds, so this self-heals; just count it.
            self._orphan_updates += 1
            self._log("debug", f"LoRa update from {camera_id} before any announce; dropping")
            return None

        seq = self._sequence.get(camera_id, 0)
        self._sequence[camera_id] = (seq + 1) & 0xFFFFFFFF

        vector = MotionVector(
            azimuth=pkt.azimuth,
            elevation=pkt.elevation,
            intensity=LORA_DETECTION_INTENSITY,
            class_id=0,
            angular_size=pkt.angular_size,
        )
        telemetry = TelemetryPacket(
            camera_id=camera_id,
            sequence_number=seq,
            timestamp=receive_time,
            latitude=pose.latitude,
            longitude=pose.longitude,
            altitude=pose.altitude,
            orientation=pose.orientation,
            health_flags=0x07,  # LoRa update carries no health; assume nominal.
            vectors=[vector],
        )
        return ReceivedPacket(telemetry, "lora", 0, receive_time)

    # -- drain (UDPServer-compatible) --------------------------------------
    def get_packets(self, max_count: int = 100) -> List[ReceivedPacket]:
        with self._qlock:
            if not self._queue:
                return []
            if len(self._queue) <= max_count:
                out = self._queue
                self._queue = []
            else:
                out = self._queue[:max_count]
                self._queue = self._queue[max_count:]
        return out

    def get_stats(self) -> dict:
        return {
            "payloads_received": self._payloads_received,
            "packets_emitted": self._packets_emitted,
            "decode_failures": self._decode_failures,
            "orphan_updates": self._orphan_updates,
            "queue_dropped": self._queue_dropped,
            "known_nodes": len(self._poses),
            "queue_size": len(self._queue),
            "running": self._running,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    def _log(self, level: str, msg: str) -> None:
        if self._logger is not None:
            try:
                getattr(self._logger, level, self._logger.info)("lora", msg)
                return
            except Exception:
                pass
