"""
key_manager.py
PURPOSE: Manage shared secrets for authentication across the system.
"""

import os
import base64
import secrets
import time
from typing import List, Optional, Dict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class KeyMetadata:
    """Metadata for a key."""
    key: bytes
    created_at: float
    expires_at: Optional[float] = None
    comment: str = ""


@dataclass
class KeyRotationStatus:
    """Status of key rotation."""
    old_key_id: str
    new_key_id: str
    distributed_to: List[str] = field(default_factory=list)
    failed_nodes: List[str] = field(default_factory=list)
    expires_at: float = 0.0


class KeyManager:
    """
    Manage shared secrets for authentication.
    
    Features:
        - Load keys from file or environment
        - Generate new keys
        - Key rotation with grace period
        - Distribution tracking
    """
    
    # Default locations (priority order)
    DEFAULT_LOCATIONS = [
        # Environment variable checked separately
        "/etc/optical_radar/secret.key",
        "./config/secret.key",
        "./secrets/shared.key",
    ]
    
    def __init__(self, key_file: Optional[str] = None):
        """
        Initialize key manager.
        
        Args:
            key_file: Path to key file. If None, searches default locations.
        """
        self._keys: List[KeyMetadata] = []
        self._key_file = key_file
        
        if key_file:
            if os.path.exists(key_file):
                self.load_keys(key_file)
        else:
            self._load_from_defaults()
    
    def _load_from_defaults(self) -> None:
        """Try to load keys from default locations."""
        # Try environment variable first
        env_key = os.environ.get('OPTICAL_RADAR_SECRET_KEY')
        if env_key:
            try:
                key = base64.b64decode(env_key)
                self._keys.append(KeyMetadata(
                    key=key,
                    created_at=time.time(),
                    comment="From environment"
                ))
                return
            except Exception:
                pass
        
        # Try file locations
        for path in self.DEFAULT_LOCATIONS:
            if os.path.exists(path):
                try:
                    self.load_keys(path)
                    self._key_file = path
                    return
                except Exception:
                    continue
    
    def load_keys(self, path: str) -> None:
        """
        Load keys from file.
        
        Format:
            - Base64-encoded key per line
            - Comments start with #
            - Can include expiry: key,expires_timestamp
        """
        self._keys = []
        
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                parts = line.split(',')
                key_b64 = parts[0].strip()
                
                try:
                    key = base64.b64decode(key_b64)
                except Exception:
                    continue
                
                if len(key) < 32:
                    continue
                
                expires_at = None
                if len(parts) > 1:
                    try:
                        expires_at = float(parts[1].strip())
                    except ValueError:
                        pass
                
                self._keys.append(KeyMetadata(
                    key=key,
                    created_at=time.time(),
                    expires_at=expires_at
                ))
    
    def save_keys(self, path: Optional[str] = None) -> None:
        """
        Save keys to file with secure permissions.
        
        Args:
            path: File path. Uses loaded path if None.
        """
        path = path or self._key_file
        if not path:
            raise ValueError("No key file path specified")
        
        # Create directory if needed
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        
        # Write keys
        lines = [f"# Generated {time.strftime('%Y-%m-%d %H:%M:%S')}"]
        for km in self._keys:
            key_b64 = base64.b64encode(km.key).decode('ascii')
            if km.expires_at:
                lines.append(f"{key_b64},{km.expires_at}")
            else:
                lines.append(key_b64)
        
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        
        # Set secure permissions (Unix only)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    
    @property
    def primary_key(self) -> Optional[bytes]:
        """Get primary (most recent, non-expired) key."""
        now = time.time()
        for km in self._keys:
            if km.expires_at is None or km.expires_at > now:
                return km.key
        return None
    
    @property
    def all_valid_keys(self) -> List[bytes]:
        """Get all non-expired keys."""
        now = time.time()
        return [km.key for km in self._keys 
                if km.expires_at is None or km.expires_at > now]
    
    def generate_key(self, length: int = 32) -> bytes:
        """
        Generate a new cryptographically secure key.
        
        Args:
            length: Key length in bytes
        
        Returns:
            New random key
        """
        return secrets.token_bytes(max(32, length))
    
    def rotate_keys(
        self,
        new_key: Optional[bytes] = None,
        grace_period_days: int = 7
    ) -> KeyRotationStatus:
        """
        Rotate to a new key while keeping old key valid.
        
        Args:
            new_key: New key to use. Generated if None.
            grace_period_days: How long old key remains valid.
        
        Returns:
            Rotation status
        """
        new_key = new_key or self.generate_key()
        now = time.time()
        expires_at = now + (grace_period_days * 86400)
        
        # Mark old keys as expiring
        old_key_id = ""
        for km in self._keys:
            if km.expires_at is None:
                km.expires_at = expires_at
                old_key_id = base64.b64encode(km.key[:4]).decode('ascii')
        
        # Add new key at front (primary)
        self._keys.insert(0, KeyMetadata(
            key=new_key,
            created_at=now,
            comment="Rotated key"
        ))
        
        new_key_id = base64.b64encode(new_key[:4]).decode('ascii')
        
        return KeyRotationStatus(
            old_key_id=old_key_id,
            new_key_id=new_key_id,
            expires_at=expires_at
        )
    
    def cleanup_expired(self) -> int:
        """
        Remove expired keys.
        
        Returns:
            Number of keys removed
        """
        now = time.time()
        original_count = len(self._keys)
        self._keys = [km for km in self._keys 
                     if km.expires_at is None or km.expires_at > now]
        return original_count - len(self._keys)
    
    def distribute_key_ssh(
        self,
        host: str,
        key: bytes,
        remote_path: str = "/etc/optical_radar/secret.key",
        username: str = "pi"
    ) -> bool:
        """
        Distribute key to remote node via SSH.
        
        Args:
            host: Remote hostname or IP
            key: Key to distribute
            remote_path: Path on remote machine
            username: SSH username
        
        Returns:
            True if successful
        """
        import subprocess
        
        key_b64 = base64.b64encode(key).decode('ascii')
        
        # Create remote file with secure permissions
        cmd = f'echo "{key_b64}" > {remote_path} && chmod 600 {remote_path}'
        
        try:
            result = subprocess.run(
                ['ssh', f'{username}@{host}', cmd],
                capture_output=True,
                timeout=30
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def verify_sync(
        self,
        hosts: List[str],
        username: str = "pi"
    ) -> Dict[str, bool]:
        """
        Verify key synchronization across nodes.
        
        Args:
            hosts: List of hostnames to check
            username: SSH username
        
        Returns:
            Dict of host -> sync status
        """
        import subprocess
        
        primary = self.primary_key
        if not primary:
            return {h: False for h in hosts}
        
        expected = base64.b64encode(primary).decode('ascii')
        results = {}
        
        for host in hosts:
            try:
                result = subprocess.run(
                    ['ssh', f'{username}@{host}', 
                     'cat /etc/optical_radar/secret.key | head -n1 | grep -v "^#"'],
                    capture_output=True,
                    timeout=10,
                    text=True
                )
                remote_key = result.stdout.strip().split(',')[0]
                results[host] = (remote_key == expected)
            except Exception:
                results[host] = False
        
        return results
