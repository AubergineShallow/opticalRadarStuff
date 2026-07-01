
"""
authenticator.py
PURPOSE: HMAC-based authentication for telemetry packets.
"""

import hmac
import hashlib
import time
import os
from typing import Optional, Tuple
from dataclasses import dataclass

import sys
import os
_parent = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from common.protocol import TelemetryPacket, SIGNATURE_SIZE


class AuthenticationError(Exception):
    """Raised when packet authentication fails."""
    pass


@dataclass
class AuthResult:
    """Result of authentication check."""
    valid: bool
    reason: str = ""
    packet: Optional[TelemetryPacket] = None


class Authenticator:
    """
    HMAC-SHA256 authenticator for telemetry packets.
    
    Provides:
        - Packet signing (camera side)
        - Packet verification (server side)
        - Replay attack prevention via timestamp
    """
    
    def __init__(
        self,
        key: Optional[bytes] = None,
        key_file: Optional[str] = None,
        max_timestamp_drift_sec: float = 30.0,
        key_manager=None
    ):
        """
        Initialize authenticator.

        Args:
            key: Shared secret key (raw bytes)
            key_file: Path to key file (alternative to key)
            max_timestamp_drift_sec: Max allowed age of packets
            key_manager: Optional KeyManager that owns key storage/rotation.
                When provided, verification keys are looked up from it per
                node_id (P5.1), so there is a single key-management implementation.
        """
        self._keys: list[bytes] = []
        self.max_timestamp_drift = max_timestamp_drift_sec
        self.key_manager = key_manager

        if key:
            self._keys = [key]
        elif key_file:
            self.load_keys_from_file(key_file)
        elif key_manager is None:
            # Try environment variable (only when not delegating to a KeyManager)
            env_key = os.environ.get('OPTICAL_RADAR_SECRET_KEY')
            if env_key:
                self._keys = [self._decode_key(env_key)]

    def _verification_keys(self, node_id: Optional[str] = None) -> list:
        """Keys to try when verifying — from the KeyManager if injected."""
        if self.key_manager is not None:
            return self.key_manager.get_valid_keys(node_id)
        return self._keys
    
    def _decode_key(self, key_str: str) -> bytes:
        """Decode base64 key string to bytes."""
        import base64
        return base64.b64decode(key_str)
    
    def load_keys_from_file(self, path: str) -> None:
        """
        Load keys from file.
        
        File format:
            - One base64-encoded key per line
            - Lines starting with # are comments
            - First non-comment key is primary
        """
        import base64
        
        if not os.path.exists(path):
            raise FileNotFoundError(f"Key file not found: {path}")
        
        # Security check: file permissions (Unix only)
        if hasattr(os, 'stat'):
            import stat
            mode = os.stat(path).st_mode
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                # File is group/world readable - warning but continue
                import warnings
                warnings.warn(f"Key file {path} has insecure permissions")
        
        self._keys = []
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                try:
                    key = base64.b64decode(line)
                    if len(key) >= 32:
                        self._keys.append(key)
                except Exception:
                    continue
        
        if not self._keys:
            raise ValueError(f"No valid keys found in {path}")
    
    @property
    def primary_key(self) -> bytes:
        """Get primary key for signing."""
        if not self._keys:
            raise RuntimeError("No keys loaded")
        return self._keys[0]
    
    @property
    def all_keys(self) -> list[bytes]:
        """Get all valid keys for verification."""
        return self._keys
    
    def sign(self, data: bytes) -> bytes:
        """
        Calculate HMAC-SHA256 signature.
        
        Args:
            data: Data to sign
        
        Returns:
            32-byte signature
        """
        return hmac.new(self.primary_key, data, hashlib.sha256).digest()
    
    def verify(self, data: bytes, signature: bytes, node_id: Optional[str] = None) -> bool:
        """
        Verify signature using constant-time comparison.

        Args:
            data: Original data
            signature: Claimed signature
            node_id: Node whose key(s) to verify against (KeyManager lookup)

        Returns:
            True if signature is valid
        """
        # Try all valid keys (for rotation support / KeyManager grace window)
        for key in self._verification_keys(node_id):
            expected = hmac.new(key, data, hashlib.sha256).digest()
            if hmac.compare_digest(expected, signature):
                return True
        return False

    def verify_telemetry_packet(self, packet: TelemetryPacket) -> bool:
        """
        Verify an already-unpacked TelemetryPacket (signature + replay window).

        This is the object-level entry point used by server_main. Keys are
        looked up per packet.camera_id via the injected KeyManager (P5.1).

        Args:
            packet: TelemetryPacket carrying .signature and .camera_id

        Returns:
            True if the packet is authentic and fresh.
        """
        signature = getattr(packet, 'signature', None)
        if not signature:
            return False

        data = packet.get_data_for_signing()
        if not self.verify(data, signature, node_id=getattr(packet, 'camera_id', None)):
            return False

        # Replay prevention
        drift = abs(time.time() - packet.timestamp)
        if drift > self.max_timestamp_drift:
            return False

        return True
    
    def sign_packet(self, packet: TelemetryPacket) -> TelemetryPacket:
        """
        Sign a telemetry packet.
        
        Args:
            packet: Packet to sign
        
        Returns:
            Packet with signature attached
        """
        data = packet.get_data_for_signing()
        packet.signature = self.sign(data)
        return packet
    
    def verify_packet(self, data: bytes) -> AuthResult:
        """
        Verify and unpack a signed packet.
        
        Args:
            data: Raw packet bytes (including signature)
        
        Returns:
            AuthResult with validity and unpacked packet
        """
        if len(data) < SIGNATURE_SIZE + 60:  # header + signature
            return AuthResult(False, "Packet too short")
        
        # Extract signature (last 32 bytes)
        packet_data = data[:-SIGNATURE_SIZE]
        signature = data[-SIGNATURE_SIZE:]
        
        # Verify signature
        if not self.verify(packet_data, signature):
            return AuthResult(False, "Invalid signature")
        
        # Unpack packet
        try:
            packet = TelemetryPacket.unpack(packet_data, has_signature=False)
        except Exception as e:
            return AuthResult(False, f"Packet parse error: {e}")
        
        # Check timestamp (replay prevention)
        now = time.time()
        drift = abs(now - packet.timestamp)
        if drift > self.max_timestamp_drift:
            return AuthResult(False, f"Timestamp too old: {drift:.1f}s drift")
        
        return AuthResult(True, "OK", packet)
    
    @staticmethod
    def generate_key(length: int = 32) -> bytes:
        """
        Generate a cryptographically secure random key.
        
        Args:
            length: Key length in bytes (min 32)
        
        Returns:
            Random key bytes
        """
        import secrets
        return secrets.token_bytes(max(32, length))
    
    @staticmethod
    def key_to_base64(key: bytes) -> str:
        """Convert key to base64 string for storage."""
        import base64
        return base64.b64encode(key).decode('ascii')
