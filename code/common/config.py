

"""
config.py
PURPOSE: Centralized configuration management for Server and Nodes.
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SystemConfig:
    version: int = 3
    debug_mode: bool = False
    headless: bool = False  # If true: compute only, no vision


@dataclass
class NetworkConfig:
    server_ip: str = "0.0.0.0"
    udp_port: int = 5005
    # Max UDP datagram. 512 silently truncated dense telemetry packets
    # (300 vectors ~= 2.5 KB) inside recvfrom(); use the full UDP ceiling.
    max_packet_size: int = 65535
    # Upper bound on distinct registered/pending nodes. Guards the optics,
    # pending and health registries against floods of unique camera_ids.
    max_nodes: int = 256


@dataclass
class SecurityConfig:
    # Opt-in. Edge nodes ship unsigned, so a default of True silently dropped
    # ALL real telemetry (BUG-008). Enable explicitly once a shared key has
    # been provisioned (provision_node.py) on both server and nodes.
    enabled: bool = False
    key_file: str = "secrets/shared.key"
    auth_timeout_sec: int = 30


@dataclass
class TrackingConfig:
    max_tracks: int = 100
    min_hits_to_confirm: int = 3
    max_misses_to_delete: int = 30
    distance_threshold_m: float = 5.0
    q_process_noise: float = 0.1
    r_measurement_noise: float = 2.0


@dataclass
class GridConfig:
    width_m: float = 200.0
    depth_m: float = 200.0  # North-South dimension
    height_m: float = 100.0  # Vertical dimension
    resolution_m: float = 1.0
    decay_rate: float = 0.95
    hot_threshold: float = 5.0


@dataclass
class MonitoringConfig:
    log_level: str = "INFO"
    log_file: str = "logs/sys.log"
    metrics_enabled: bool = True
    prometheus_port: int = 8000


@dataclass
class CalibrationConfig:
    """Self-calibration feedback loop (P1.5)."""
    enabled: bool = True
    buffer_size: int = 2000
    solve_interval: float = 10.0        # seconds between solves
    blend_factor: float = 0.1           # correction blend factor [0, 1]
    max_correction_degrees: float = 15.0
    min_observations: int = 100
    min_track_hits: int = 3             # only feed confirmed tracks
    association_radius_m: float = 10.0  # max ray-to-track distance to associate
    offsets_file: str = "secrets/calibration_offsets.json"


@dataclass
class GPSConfig:
    port: str = "/dev/serial0"
    baud_rate: int = 9600


@dataclass
class IMUConfig:
    i2c_address: int = 0x68
    calibration_samples: int = 100


@dataclass
class FoxgloveConfig:
    """Optional Foxglove/Flora live-streaming add-on (parallel broadcaster).

    Off by default: a future `pip install foxglove-sdk` must not silently start
    streaming camera/track data. Enable explicitly to open the second listening
    socket. Env overrides work automatically: OR_FOXGLOVE_ENABLED=true /
    OR_FOXGLOVE_PORT=...
    """
    enabled: bool = False
    port: int = 8765


@dataclass
class LoRaConfig:
    """Optional LoRa / Meshtastic ingest gateway (server.lora_gateway).

    Off by default: a laptop-as-server cannot receive LoRa without a radio
    physically attached, so enabling this only makes sense once a Meshtastic
    node (USB) or an SX127x serial bridge is present. Env overrides work:
    OR_LORA_ENABLED=true / OR_LORA_TRANSPORT=meshtastic / OR_LORA_DEVICE=COM7 ...
    """
    enabled: bool = False
    # "meshtastic" (radio over USB, mesh relaying) | "serial" (raw SX127x
    # bridge) | "udp" (ESP32 WiFi fallback) | "loopback" (in-process, tests).
    transport: str = "meshtastic"
    device: str = ""             # serial device / meshtastic devPath ("" = auto)
    baud: int = 115200           # used by the "serial" transport
    udp_port: int = 5006         # used by the "udp" transport (not 5005 = V3 UDP)
    tcp_host: str = ""           # set to use a TCP-attached meshtastic node
    portnum: int = 256           # meshtastic PRIVATE_APP port (both ends agree)
    channel_index: int = 0       # meshtastic channel index
    node_id_prefix: str = "lora"  # uint8 node id -> camera_id (5 -> "lora05")


@dataclass
class ServerConfig:
    """Server runtime settings."""
    ws_port: int = 5000          # MUST match the frontend Env.WS_URL
    target_fps: int = 30


@dataclass
class ReferenceConfig:
    """ENU reference origin.

    MUST match the frontend COORDINATE_ORIGIN so backend ENU positions and the
    map overlay share one coordinate frame. A (0,0,0) origin put every realistic
    GPS node thousands of km outside the voxel grid, so nothing was ever tracked.
    """
    origin_lat: float = 37.7749   # San Francisco (matches NEW-UI-V2/constants.ts)
    origin_lon: float = -122.4194
    origin_alt: float = 0.0


@dataclass
class Config:
    """Root configuration object."""
    system: SystemConfig = field(default_factory=SystemConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    reference: ReferenceConfig = field(default_factory=ReferenceConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    grid: GridConfig = field(default_factory=GridConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    gps: GPSConfig = field(default_factory=GPSConfig)
    imu: IMUConfig = field(default_factory=IMUConfig)
    foxglove: FoxgloveConfig = field(default_factory=FoxgloveConfig)
    lora: LoRaConfig = field(default_factory=LoRaConfig)


def _apply_env_overrides(config: Config) -> Config:
    """Apply environment variable overrides (OR_SECTION_KEY=value)."""
    prefix = "OR_"
    
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        
        parts = key[len(prefix):].lower().split("_", 1)
        if len(parts) != 2:
            continue
        
        section, param = parts
        
        if hasattr(config, section):
            section_obj = getattr(config, section)
            if hasattr(section_obj, param):
                current = getattr(section_obj, param)
                # Type conversion based on current type
                if isinstance(current, bool):
                    setattr(section_obj, param, value.lower() in ("true", "1", "yes"))
                elif isinstance(current, int):
                    setattr(section_obj, param, int(value))
                elif isinstance(current, float):
                    setattr(section_obj, param, float(value))
                else:
                    setattr(section_obj, param, value)
    
    return config


def _build_section(cls, section_name: str, data: dict):
    """Construct a config dataclass from a YAML section, tolerating unknown keys.

    A typo'd or newer-version key used to raise TypeError and abort startup;
    now it is dropped with a warning and the rest of the section still applies.
    """
    import dataclasses
    known = {f.name for f in dataclasses.fields(cls)}
    unknown = set(data) - known
    if unknown:
        print(f"Warning: ignoring unknown config key(s) in '{section_name}': "
              f"{', '.join(sorted(unknown))}")
    return cls(**{k: v for k, v in data.items() if k in known})


def load(path: Optional[str] = None) -> Config:
    """
    Load configuration from YAML file with environment overrides.

    Args:
        path: Path to config.yaml. If None, uses defaults.

    Returns:
        Config object with all settings.
    """
    config = Config()

    if path and os.path.exists(path):
        with open(path, 'r') as f:
            data = yaml.safe_load(f) or {}

        # Populate from YAML (section name -> dataclass on Config)
        sections = {
            'system': SystemConfig,
            'network': NetworkConfig,
            'server': ServerConfig,
            'reference': ReferenceConfig,
            'security': SecurityConfig,
            'tracking': TrackingConfig,
            'grid': GridConfig,
            'monitoring': MonitoringConfig,
            'calibration': CalibrationConfig,
            'gps': GPSConfig,
            'imu': IMUConfig,
            'foxglove': FoxgloveConfig,
            'lora': LoRaConfig,
        }
        for name, cls in sections.items():
            if name in data and isinstance(data[name], dict):
                setattr(config, name, _build_section(cls, name, data[name]))

    # Apply environment overrides
    config = _apply_env_overrides(config)

    return config


# Global config instance (lazy loaded)
_config: Optional[Config] = None


def get_config(path: Optional[str] = None) -> Config:
    """Get the global config instance, loading if necessary."""
    global _config
    if _config is None:
        _config = load(path)
    return _config
