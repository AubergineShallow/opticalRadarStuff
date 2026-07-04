"""
lora_link.py
PURPOSE: Transport abstraction for the compressed LoRa payloads defined in
         common.lora_protocol. One interface, three backends, so the server
         gateway and the RPi node do not care how the bytes actually move.

Backends
--------
  * MeshtasticTransport - PRIMARY. Talks to a Meshtastic radio attached to the
    host over USB serial (or TCP/BLE) using the `meshtastic` Python library.
    Our payload rides as the app payload of a mesh data packet on a dedicated
    PortNum, so Meshtastic's own routing / mesh relaying carries it for free.
    Requires: pip install meshtastic  (optional; imported lazily).

  * SerialLoRaTransport - a raw point-to-point / star SX127x link exposed to the
    host as a serial byte stream (e.g. an ESP32/RP2040 running a serial<->LoRa
    bridge sketch, or a LoRa HAT). Uses LoRaFramer for message boundaries.
    Requires: pip install pyserial  (optional; imported lazily).

  * LoopbackTransport - in-process queue. No hardware, no optional deps; used by
    system_test.py and for wiring two components together in one process.

Every backend implements:
    start() -> bool
    stop()  -> None
    send(payload: bytes) -> bool
    poll()  -> List[bytes]      # complete, ready-to-decode LoRa payloads
    is_running -> bool
"""

import threading
import time
from collections import deque
from typing import Deque, List, Optional

from common.lora_protocol import LoRaFramer, frame_payload

# Meshtastic PortNum for our private application traffic. PRIVATE_APP (256) is
# the range Meshtastic reserves for exactly this: user-defined payloads that the
# stock apps ignore. Both ends must agree on this number.
MESHTASTIC_PORTNUM = 256

# SERIAL_APP (64): the port the Meshtastic Serial Module transmits on. An
# ESP32-CAM that hands its payload to a companion Meshtastic node over UART
# (Serial Module) arrives here, so the gateway accepts it too. Payloads from a
# node using the Python API directly (the RPi path) arrive on PRIVATE_APP.
MESHTASTIC_SERIAL_APP_PORTNUM = 64


class LoRaTransport:
    """Base interface. Subclasses override start/stop/send/poll."""

    def start(self) -> bool:
        return True

    def stop(self) -> None:
        pass

    def send(self, payload: bytes) -> bool:
        raise NotImplementedError

    def poll(self) -> List[bytes]:
        raise NotImplementedError

    @property
    def is_running(self) -> bool:
        return False


class LoopbackTransport(LoRaTransport):
    """
    In-process transport. Bytes sent are immediately available to poll() on the
    same object, or on a paired peer if one is attached with attach_peer().
    Thread-safe. Used for tests and single-process wiring.
    """

    def __init__(self):
        self._inbox: Deque[bytes] = deque()
        self._lock = threading.Lock()
        self._peer: Optional["LoopbackTransport"] = None
        self._running = False

    def attach_peer(self, peer: "LoopbackTransport") -> None:
        """Deliver everything sent here into `peer`'s inbox (and vice versa)."""
        self._peer = peer
        peer._peer = self

    def start(self) -> bool:
        self._running = True
        return True

    def stop(self) -> None:
        self._running = False

    def send(self, payload: bytes) -> bool:
        target = self._peer if self._peer is not None else self
        with target._lock:
            target._inbox.append(bytes(payload))
        return True

    def poll(self) -> List[bytes]:
        with self._lock:
            out = list(self._inbox)
            self._inbox.clear()
        return out

    @property
    def is_running(self) -> bool:
        return self._running


class MeshtasticTransport(LoRaTransport):
    """
    Receive/transmit our payloads through a locally-attached Meshtastic radio.

    The `meshtastic` library runs its own serial reader thread and calls our
    onReceive callback for every mesh packet; we filter to MESHTASTIC_PORTNUM
    and queue the raw payload bytes for poll(). Sending injects a data packet on
    the same PortNum, which the mesh relays to the rest of the network.
    """

    def __init__(
        self,
        device: Optional[str] = None,
        portnum: int = MESHTASTIC_PORTNUM,
        channel_index: int = 0,
        tcp_host: Optional[str] = None,
    ):
        self.device = device            # e.g. "COM7" / "/dev/ttyUSB0"; None = auto
        self.portnum = portnum
        self.channel_index = channel_index
        self.tcp_host = tcp_host         # set to use a TCP-attached node instead
        # Accept our private port (RPi Python-API path) AND the Serial Module
        # port (ESP32 companion-node path), each as int or enum-name.
        self._accept_ports = {
            portnum, MESHTASTIC_SERIAL_APP_PORTNUM,
            "PRIVATE_APP", "SERIAL_APP",
        }
        self._iface = None
        self._pubsub = None
        self._inbox: Deque[bytes] = deque()
        self._lock = threading.Lock()
        self._running = False

    def start(self) -> bool:
        try:
            import meshtastic
            import meshtastic.serial_interface as serial_interface
            from pubsub import pub
        except ImportError as e:
            raise RuntimeError(
                "MeshtasticTransport needs the 'meshtastic' package "
                "(pip install meshtastic). Original error: %s" % e
            )

        if self.tcp_host:
            import meshtastic.tcp_interface as tcp_interface
            self._iface = tcp_interface.TCPInterface(hostname=self.tcp_host)
        else:
            self._iface = serial_interface.SerialInterface(devPath=self.device)

        self._pubsub = pub
        pub.subscribe(self._on_receive, "meshtastic.receive.data")
        self._running = True
        return True

    def _on_receive(self, packet=None, interface=None):  # pragma: no cover - needs hw
        try:
            decoded = (packet or {}).get("decoded", {})
            # Some meshtastic lib versions report portnum as an int, others as
            # the enum name. Accept our private port or the Serial Module port.
            if decoded.get("portnum") not in self._accept_ports:
                return
            payload = decoded.get("payload")
            if payload:
                with self._lock:
                    self._inbox.append(bytes(payload))
        except Exception:
            pass

    def send(self, payload: bytes) -> bool:  # pragma: no cover - needs hw
        if not self._iface:
            return False
        try:
            self._iface.sendData(
                bytes(payload),
                portNum=self.portnum,
                channelIndex=self.channel_index,
                wantAck=False,
            )
            return True
        except Exception:
            return False

    def poll(self) -> List[bytes]:
        with self._lock:
            out = list(self._inbox)
            self._inbox.clear()
        return out

    def stop(self) -> None:
        self._running = False
        if self._pubsub is not None:
            try:
                self._pubsub.unsubscribe(self._on_receive, "meshtastic.receive.data")
            except Exception:
                pass
        if self._iface is not None:
            try:
                self._iface.close()
            except Exception:
                pass
            self._iface = None

    @property
    def is_running(self) -> bool:
        return self._running


class SerialLoRaTransport(LoRaTransport):
    """
    Raw serial byte stream to an SX127x bridge / LoRa HAT. Frames outgoing
    payloads and deframes the incoming stream with LoRaFramer in a reader
    thread.
    """

    def __init__(self, port: str, baud: int = 115200, read_timeout: float = 0.1):
        self.port = port
        self.baud = baud
        self.read_timeout = read_timeout
        self._serial = None
        self._framer = LoRaFramer()
        self._inbox: Deque[bytes] = deque()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> bool:
        try:
            import serial  # pyserial
        except ImportError as e:
            raise RuntimeError(
                "SerialLoRaTransport needs 'pyserial' (pip install pyserial). "
                "Original error: %s" % e
            )
        self._serial = serial.Serial(self.port, self.baud, timeout=self.read_timeout)
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        return True

    def _reader(self) -> None:  # pragma: no cover - needs hw
        while self._running:
            try:
                data = self._serial.read(256)
                if data:
                    payloads = self._framer.push(data)
                    if payloads:
                        with self._lock:
                            self._inbox.extend(payloads)
                else:
                    time.sleep(0.005)
            except Exception:
                time.sleep(0.05)

    def send(self, payload: bytes) -> bool:  # pragma: no cover - needs hw
        if not self._serial:
            return False
        try:
            self._serial.write(frame_payload(payload))
            return True
        except Exception:
            return False

    def poll(self) -> List[bytes]:
        with self._lock:
            out = list(self._inbox)
            self._inbox.clear()
        return out

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    @property
    def is_running(self) -> bool:
        return self._running


class UDPLoRaTransport(LoRaTransport):
    """
    Receive compressed LoRa payloads over UDP. This is the server end of the
    ESP32-CAM's WiFi/UDP fallback backend: each datagram carries exactly one
    unframed payload (UDP is already message-oriented, so no LoRaFramer needed).

    Bound to its own port (default 5006) so it never collides with the primary
    V3 telemetry UDPServer on 5005.
    """

    def __init__(self, port: int = 5006, bind_addr: str = "0.0.0.0"):
        self.port = port
        self.bind_addr = bind_addr
        self._socket = None
        self._inbox: Deque[bytes] = deque()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> bool:
        import socket
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.bind_addr, self.port))
        self._socket.settimeout(0.1)
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        return True

    def _reader(self) -> None:
        import socket as _socket
        while self._running:
            try:
                data, _addr = self._socket.recvfrom(512)
                if data:
                    with self._lock:
                        self._inbox.append(bytes(data))
            except _socket.timeout:
                continue
            except Exception:
                if self._running:
                    time.sleep(0.02)

    def send(self, payload: bytes) -> bool:
        # The gateway only ingests; sending downstream over UDP is not used.
        return False

    def poll(self) -> List[bytes]:
        with self._lock:
            out = list(self._inbox)
            self._inbox.clear()
        return out

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    @property
    def is_running(self) -> bool:
        return self._running


def make_transport(kind: str, **kwargs) -> LoRaTransport:
    """
    Factory used by config-driven callers.

    kind: "meshtastic" | "serial" | "udp" | "loopback"
    kwargs are forwarded to the backend constructor.
    """
    kind = (kind or "loopback").strip().lower()
    if kind == "meshtastic":
        return MeshtasticTransport(
            device=kwargs.get("device"),
            portnum=kwargs.get("portnum", MESHTASTIC_PORTNUM),
            channel_index=kwargs.get("channel_index", 0),
            tcp_host=kwargs.get("tcp_host"),
        )
    if kind == "serial":
        port = kwargs.get("port")
        if not port:
            # pyserial accepts port=None (creates an unopened Serial), which
            # left the reader thread spinning on a closed port forever with no
            # diagnostic. Fail at configuration time instead.
            raise ValueError(
                "serial LoRa transport requires a device (config lora.device "
                "/ OR_LORA_DEVICE, e.g. COM7 or /dev/ttyUSB0)")
        return SerialLoRaTransport(
            port=port,
            baud=kwargs.get("baud", 115200),
        )
    if kind == "udp":
        return UDPLoRaTransport(
            port=kwargs.get("udp_port", 5006),
            bind_addr=kwargs.get("bind_addr", "0.0.0.0"),
        )
    if kind == "loopback":
        return LoopbackTransport()
    raise ValueError(f"Unknown LoRa transport kind: {kind!r}")
