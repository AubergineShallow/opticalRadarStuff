
"""
node_specs.py
PURPOSE: Load per-node optical specifications from a JSON registry file.

A node's angular (bearing) uncertainty is a function of its optics -- field of
view divided by sensor resolution -- which is a fixed physical property of the
lens+sensor assembly. Crucially, embedded modules (Raspberry Pi Camera, an
ESP32-CAM) cannot read the lens focal length / FOV back electronically: the
sensor silicon has no idea what glass sits in front of it. So the spec must be
*provisioned*, not queried.

Rather than bury those numbers as inline constants in each node's source (the
previous approach), they live in one JSON file (config/node_specs.json) keyed by
node id:

  - each node loads its own entry at startup and uses it to fill its
    AnnouncePacket (FOV / resolution / fps), and
  - the server loads the whole file as a fallback optics source for any node
    that has not announced yet.

JSON (not YAML) is deliberate: it needs no third-party dependency and parses on
constrained targets (MicroPython, a C++ ESP32 JSON library) as well as CPython,
so one file format serves every node type. Missing file / missing entry degrades
gracefully to a built-in default, so the system still runs out of the box.
"""

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, Optional

DEFAULT_KEY = "_default"


def _default_path() -> str:
    """Resolve the spec file: OR_NODE_SPECS_FILE env override, else the
    repo's code/config/node_specs.json (this module lives in code/common/)."""
    env = os.environ.get("OR_NODE_SPECS_FILE")
    if env:
        return env
    code_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(code_dir, "config", "node_specs.json")


@dataclass
class NodeSpec:
    """Optical specification for one node."""
    node_id: str
    sensor: str = "generic"
    fov_horizontal: float = 60.0
    fov_vertical: float = 45.0
    resolution_width: int = 640
    resolution_height: int = 480

    @property
    def sigma_theta_rad(self) -> float:
        """1-sigma bearing uncertainty (radians).

        Approximated as the angular subtense of a single pixel on the coarser
        of the two axes -- a conservative default (a well-centred centroid is
        often better than a pixel; a smeared blob worse). This is the quantity
        the server turns into a positional measurement covariance.
        """
        h = self.fov_horizontal / max(self.resolution_width, 1)
        v = self.fov_vertical / max(self.resolution_height, 1)
        return math.radians(max(h, v))

    @classmethod
    def from_dict(cls, node_id: str, d: dict) -> "NodeSpec":
        return cls(
            node_id=node_id,
            sensor=str(d.get("sensor", "generic")),
            fov_horizontal=float(d.get("fov_horizontal", 60.0)),
            fov_vertical=float(d.get("fov_vertical", 45.0)),
            resolution_width=int(d.get("resolution_width", 640)),
            resolution_height=int(d.get("resolution_height", 480)),
        )


def _read(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_all_specs(path: Optional[str] = None) -> Dict[str, NodeSpec]:
    """Load every real node entry (metadata keys like '_default'/'_comment'
    are skipped). Returns an empty dict if the file is missing/unreadable."""
    data = _read(path or _default_path())
    out: Dict[str, NodeSpec] = {}
    for key, val in data.items():
        if key.startswith("_"):
            continue
        if isinstance(val, dict):
            out[key] = NodeSpec.from_dict(key, val)
    return out


def default_spec(path: Optional[str] = None) -> NodeSpec:
    """Return the '_default' entry (used for unlisted node ids), or a built-in
    60x45 / 640x480 default if the file or the entry is absent."""
    data = _read(path or _default_path())
    entry = data.get(DEFAULT_KEY)
    if isinstance(entry, dict):
        return NodeSpec.from_dict(DEFAULT_KEY, entry)
    return NodeSpec(node_id=DEFAULT_KEY)


def load_node_spec(node_id: str, path: Optional[str] = None) -> NodeSpec:
    """Load one node's spec by id, falling back to '_default', then to a
    built-in default. Always returns a usable NodeSpec (never raises)."""
    resolved = path or _default_path()
    data = _read(resolved)
    entry = data.get(node_id)
    if isinstance(entry, dict):
        return NodeSpec.from_dict(node_id, entry)
    spec = default_spec(resolved)
    spec.node_id = node_id
    return spec
