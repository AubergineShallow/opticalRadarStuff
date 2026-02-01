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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

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
        max_timestamp_drift_sec: float = 30.0
    ):
        """
        Initialize authenticator.
        
        Args:
            key: Shared secret key (raw bytes)
            key_file: Path to key file (alternative to key)
            max_timestamp_drift_sec: Max allowed age of packets
        """
        self._keys: list[bytes] = []
        self.max_timestamp_drift = max_timestamp_drift_sec
        
        if key:
            self._keys = [key]
        elif key_file:
            self.load_keys_from_file(key_file)
        else:
            # Try environment variable
            env_key = os.environ.get('OPTICAL_RADAR_SECRET_KEY')
            if env_key:
                self._keys = [self._decode_key(env_key)]
    
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
    
    def verify(self, data: bytes, signature: bytes) -> bool:
        """
        Verify signature using constant-time comparison.
        
        Args:
            data: Original data
            signature: Claimed signature
        
        Returns:
            True if signature is valid
        """
        # Try all valid keys (for rotation support)
        for key in self._keys:
            expected = hmac.new(key, data, hashlib.sha256).digest()
            if hmac.compare_digest(expected, signature):
                return True
        return False
    
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
