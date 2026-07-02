

"""
voxel_grid.py
PURPOSE: Sparse hierarchical octree for accumulating ray intersections.

P2 (Hierarchical Octree) replaces the dense numpy accumulator with a sparse
octree. The grid starts as a single coarse root leaf and only subdivides a
region once it is hit by >= ``min_cameras_to_subdivide`` distinct cameras
within a co-temporal window (P2.5) — i.e. where a real multi-camera
triangulation is occurring. This keeps memory proportional to active leaves,
not to the static grid volume.

Single-resolution / single-camera behaviour reduces to a coarse grid, so the
existing tests (which fire one ray and check no-crash + list/stat shapes)
continue to pass unchanged.

Backward-compat surface retained: VoxelGridConfig, HotVoxel, VoxelGrid with
add_ray / add_rays_batch / decay / get_hot_voxels / cluster_hot_voxels /
get_detections / get_stats / reset, plus nx/ny/nz/origin aliases.
"""

import math
import numpy as np
from typing import List, Tuple, Optional, Dict, Set, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from server.ray_builder import Ray

# Import native acceleration module (kept for a possible Phase 2 native octree
# kernel — see P2.9). Phase 1 octree traversal is pure Python + NumPy.
try:
    import sys
    import os
    _parent = os.path.dirname(os.path.dirname(__file__))
    if _parent not in sys.path:
        sys.path.insert(0, _parent)
    from native import native_wrapper
    _NATIVE_MODULE = native_wrapper
except ImportError:
    _NATIVE_MODULE = None


@dataclass
class VoxelGridConfig:
    """Voxel grid configuration."""
    # --- existing fields, unchanged defaults ---
    width_m: float = 200.0   # X (East) dimension
    height_m: float = 100.0  # Z (Up) dimension
    depth_m: float = 200.0   # Y (North) dimension
    resolution_m: float = 1.0  # finest leaf cell size
    decay_rate: float = 0.95   # per-frame heat decay
    hot_threshold: float = 5.0  # minimum heat to consider "hot"

    # --- new optional fields (P2.2) ---
    root_cell_size_m: float = 0.0    # 0.0 -> derive as next_pow2(max(dims))
    level_sizes: tuple = ()          # () -> single-resolution mode
    cold_threshold: float = 0.5      # heat below which a leaf may be collapsed
    camera_window_frames: int = 10   # co-temporal window for M-camera trigger (P2.5)
    min_cameras_to_subdivide: int = 3


@dataclass
class HotVoxel:
    """A leaf above the heat threshold (octree-compatible)."""
    heat: float
    center: np.ndarray  # world coords — what callers consume
    level: int          # octree depth; 0 = root
    size_m: float       # cell size at this level


@dataclass(eq=False)
class OctreeNode:
    """
    A node in the sparse octree.

    eq=False -> identity equality + hashability, so nodes can live in a set
    (``_active_leaves``). Value equality on numpy-array fields would be
    ambiguous anyway.
    """
    bounds_min: np.ndarray              # [xmin, ymin, zmin] world coords
    bounds_max: np.ndarray              # [xmax, ymax, zmax]
    heat: float = 0.0
    level: int = 0                      # 0 = root
    parent: Optional['OctreeNode'] = None
    children: Optional[List[Optional['OctreeNode']]] = None  # None -> leaf

    # Per-node camera tracking for the subdivision trigger (P2.5):
    # {camera_id: last_frame_index}
    _recent_cameras: dict = field(default_factory=dict)

    @property
    def is_leaf(self) -> bool:
        return self.children is None

    @property
    def size(self) -> np.ndarray:
        return self.bounds_max - self.bounds_min

    @property
    def center(self) -> np.ndarray:
        return (self.bounds_min + self.bounds_max) * 0.5

    def subdivide(self) -> List['OctreeNode']:
        """Split into 8 equal children. Returns the new children."""
        mid = self.center
        self.children = []
        for xi in range(2):
            for yi in range(2):
                for zi in range(2):
                    cmin = np.array([
                        self.bounds_min[0] if xi == 0 else mid[0],
                        self.bounds_min[1] if yi == 0 else mid[1],
                        self.bounds_min[2] if zi == 0 else mid[2],
                    ])
                    cmax = np.array([
                        mid[0] if xi == 0 else self.bounds_max[0],
                        mid[1] if yi == 0 else self.bounds_max[1],
                        mid[2] if zi == 0 else self.bounds_max[2],
                    ])
                    child = OctreeNode(
                        bounds_min=cmin, bounds_max=cmax,
                        heat=self.heat / 8.0,   # distribute parent heat
                        level=self.level + 1,
                        parent=self,
                    )
                    self.children.append(child)
        return self.children

    def collapse(self) -> None:
        """Merge children back into this leaf. Caller updates _active_leaves."""
        if self.children:
            self.heat = max((c.heat for c in self.children if c is not None),
                            default=self.heat)
        self.children = None
        self._recent_cameras.clear()


class VoxelGrid:
    """
    Sparse octree accumulator for ray intersection.

    Rays add heat to the leaf cells they pass through. Where votes from
    multiple distinct cameras coincide on a cell, the cell subdivides,
    progressively localising the intersection down to ``resolution_m``.
    """

    def __init__(self, config: Optional[VoxelGridConfig] = None):
        self.config = config or VoxelGridConfig()

        # Dense-grid aliases retained for backward compat (get_stats, ENU origin).
        self.nx = int(self.config.width_m / self.config.resolution_m)
        self.ny = int(self.config.depth_m / self.config.resolution_m)
        self.nz = int(self.config.height_m / self.config.resolution_m)
        self.origin = np.array([
            -self.config.width_m / 2,
            -self.config.depth_m / 2,
            0.0,
        ])

        self._init_root()

    # ------------------------------------------------------------------ #
    # Construction / reset                                               #
    # ------------------------------------------------------------------ #
    def _root_size(self) -> float:
        """Derive the cubic root cell size from config (P2.6)."""
        max_dim = max(self.config.width_m, self.config.depth_m, self.config.height_m)
        if self.config.root_cell_size_m > 0:
            return float(self.config.root_cell_size_m)
        # Round up to next power of two for clean binary subdivision.
        return float(2 ** math.ceil(math.log2(max_dim))) if max_dim > 0 else 1.0

    def _init_root(self) -> None:
        root_size = self._root_size()
        half = root_size / 2.0
        # Cubic root: X,Y centred at 0; Z runs from ground (0) up to root_size.
        self._root = OctreeNode(
            bounds_min=np.array([-half, -half, 0.0]),
            bounds_max=np.array([half, half, root_size]),
            level=0,
        )
        self._active_leaves: Set[OctreeNode] = {self._root}

    def reset(self) -> None:
        """Clear all heat and structure back to a single root leaf."""
        self._init_root()

    # ------------------------------------------------------------------ #
    # Coordinate helpers (retained for compat)                           #
    # ------------------------------------------------------------------ #
    def world_to_grid(self, pos: np.ndarray) -> Tuple[int, int, int]:
        local = pos - self.origin
        return (
            int(local[0] / self.config.resolution_m),
            int(local[1] / self.config.resolution_m),
            int(local[2] / self.config.resolution_m),
        )

    def grid_to_world(self, ix: int, iy: int, iz: int) -> np.ndarray:
        return self.origin + np.array([
            (ix + 0.5) * self.config.resolution_m,
            (iy + 0.5) * self.config.resolution_m,
            (iz + 0.5) * self.config.resolution_m,
        ])

    def is_valid_index(self, ix: int, iy: int, iz: int) -> bool:
        return (0 <= ix < self.nx and 0 <= iy < self.ny and 0 <= iz < self.nz)

    # ------------------------------------------------------------------ #
    # Decay (P2.1): per-frame heat decay vs. throttled structural prune  #
    # ------------------------------------------------------------------ #
    def decay_active_leaves(self) -> None:
        """
        Per-frame heat decay. O(active_leaves) multiplications, zero allocation.
        Call every frame from _run_loop at full rate.
        """
        dr = self.config.decay_rate
        for leaf in self._active_leaves:
            leaf.heat *= dr

    def decay(self) -> None:
        """Backward-compat alias. Prefer decay_active_leaves() directly."""
        self.decay_active_leaves()

    def consolidate_and_prune(self) -> None:
        """
        Throttled structural housekeeping (call at ~1.5s cadence, not per frame).
        Collapses sibling leaves that have all cooled below cold_threshold back
        into their parent and frees the child nodes. No heat modification.
        """
        cold = self.config.cold_threshold
        changed = True
        while changed:
            changed = False
            # Walk internal nodes bottom-up so collapses can cascade upward.
            for node in self._internal_nodes_postorder():
                children = node.children
                if not children:
                    continue
                if all(c is not None and c.is_leaf and c.heat < cold for c in children):
                    for c in children:
                        self._active_leaves.discard(c)
                    node.collapse()
                    self._active_leaves.add(node)
                    changed = True

    def _internal_nodes_postorder(self) -> List[OctreeNode]:
        """Internal (non-leaf) nodes, deepest first."""
        result: List[OctreeNode] = []

        def rec(node: OctreeNode) -> None:
            if node.is_leaf:
                return
            for c in node.children:
                if c is not None:
                    rec(c)
            result.append(node)

        rec(self._root)
        return result

    # ------------------------------------------------------------------ #
    # Ray insertion                                                      #
    # ------------------------------------------------------------------ #
    def add_ray(
        self,
        origin: np.ndarray,
        direction: np.ndarray,
        intensity: float = 1.0,
        max_distance: float = 150.0,
        step_size: float = 0.5,   # retained for signature compat; unused
        camera_id: str = "",
        frame_index: int = 0,
    ) -> int:
        """
        Add heat along a ray through the octree.

        Returns the number of leaf cells updated.
        """
        return self._traverse_octree(
            np.asarray(origin, dtype=float),
            np.asarray(direction, dtype=float),
            float(intensity),
            camera_id,
            int(frame_index),
            float(max_distance),
        )

    def add_rays_batch(
        self,
        rays: List['Ray'],
        max_distance: float = 150.0,
        step_size: float = 0.5,
        frame_index: int = 0,
    ) -> int:
        """
        Add multiple Ray objects (from RayBuilder.build_rays_from_packet).

        Phase 1 (P2.9): pure-Python octree traversal — the native flat-grid
        kernel is structurally incompatible with variable-resolution leaves.
        """
        if not rays:
            return 0

        total = 0
        for r in rays:
            total += self.add_ray(
                r.origin, r.direction, r.intensity,
                max_distance, step_size,
                camera_id=getattr(r, 'camera_id', ''),
                frame_index=frame_index,
            )
        return total

    def _traverse_octree(
        self,
        origin: np.ndarray,
        direction: np.ndarray,
        intensity: float,
        camera_id: str,
        frame_index: int,
        max_distance: float,
    ) -> int:
        """
        Traverse the octree coarse-to-fine, depositing heat in each intersected
        leaf exactly once, and subdividing leaves that meet the M-distinct-camera
        co-temporal threshold (P2.4/P2.5).
        """
        norm = np.linalg.norm(direction)
        if norm == 0:
            return 0
        direction = direction / norm

        updated = 0
        stack: List[OctreeNode] = [self._root]

        while stack:
            node = stack.pop()

            t_min, t_max = self._ray_slab(origin, direction,
                                          node.bounds_min, node.bounds_max)
            if t_max < 0 or t_min > max_distance or t_min > t_max:
                continue

            # Altitude ceiling: derived from config, not hardcoded.
            entry_t = max(t_min, 0.0)
            if origin[2] + entry_t * direction[2] > self.config.height_m:
                continue

            if node.is_leaf:
                # Record this camera's vote. Stale votes are pruned lazily,
                # only when the leaf approaches the subdivision threshold —
                # rebuilding the dict on every ray hit (the old behaviour)
                # allocated in the hottest loop of the server.
                rc = node._recent_cameras
                rc[camera_id] = frame_index

                subdivide = False
                min_cams = self.config.min_cameras_to_subdivide
                leaf_size = float(node.size[0])
                if len(rc) >= min_cams and leaf_size > self.config.resolution_m:
                    window = self.config.camera_window_frames
                    stale = [cid for cid, f in rc.items() if frame_index - f > window]
                    for cid in stale:
                        del rc[cid]
                    subdivide = len(rc) >= min_cams

                if subdivide:
                    # Don't deposit into the parent: the ray re-traverses the
                    # new children and deposits there. Depositing in both (the
                    # old behaviour) double-counted this ray at the split site
                    # (children also inherit heat/8 from the parent).
                    children = node.subdivide()
                    self._active_leaves.discard(node)
                    self._active_leaves.update(children)
                    stack.extend(children)  # re-traverse this ray into children
                else:
                    node.heat += intensity
                    updated += 1
            else:
                for c in node.children:
                    if c is None:
                        continue
                    ct_min, ct_max = self._ray_slab(origin, direction,
                                                    c.bounds_min, c.bounds_max)
                    if ct_max >= 0 and ct_min <= max_distance and ct_min <= ct_max:
                        stack.append(c)

        return updated

    @staticmethod
    def _ray_slab(
        origin: np.ndarray,
        direction: np.ndarray,
        box_min: np.ndarray,
        box_max: np.ndarray,
    ) -> Tuple[float, float]:
        """
        Ray-AABB slab test. Returns (t_enter, t_exit); t_enter > t_exit means
        no intersection. t_enter < 0 means the origin is inside the box.

        Axis-aligned rays (a zero direction component) are handled explicitly:
        a ray parallel to a slab only intersects the box if its origin lies
        within that slab. (The naive vectorised form treats every box as
        spanning the zero axis, which makes an axis-aligned ray "hit" every
        off-path cell.)
        """
        t_enter = -np.inf
        t_exit = np.inf
        for a in range(3):
            d = direction[a]
            if d != 0.0:
                ta = (box_min[a] - origin[a]) / d
                tb = (box_max[a] - origin[a]) / d
                lo, hi = (ta, tb) if ta <= tb else (tb, ta)
                if lo > t_enter:
                    t_enter = lo
                if hi < t_exit:
                    t_exit = hi
            else:
                # Parallel to this slab: must be inside it to intersect at all.
                if origin[a] < box_min[a] or origin[a] > box_max[a]:
                    return (np.inf, -np.inf)
        return (float(t_enter), float(t_exit))

    # ------------------------------------------------------------------ #
    # Directional root expansion (P2.7)                                  #
    # ------------------------------------------------------------------ #
    def expand_root(self, breach_position: np.ndarray) -> None:
        """
        Double the octree bounds toward a breach. The old root becomes a child
        of a new super-root; existing leaf world coordinates are preserved
        exactly (no translation).
        """
        breach_position = np.asarray(breach_position, dtype=float)
        old_root = self._root
        old_min = old_root.bounds_min.copy()
        old_max = old_root.bounds_max.copy()
        old_size = old_max - old_min

        breach_positive = breach_position > (old_min + old_size * 0.9)
        breach_negative = breach_position < (old_min + old_size * 0.1)

        new_min = old_min.copy()
        new_max = old_max.copy()
        for axis in range(3):
            if breach_positive[axis]:
                new_max[axis] += old_size[axis]
            elif breach_negative[axis]:
                new_min[axis] -= old_size[axis]

        super_root = OctreeNode(
            bounds_min=new_min,
            bounds_max=new_max,
            level=old_root.level - 1,
            children=[None] * 8,
        )

        # Place the old root in the octant opposite the breach so its leaves
        # keep their world coordinates.
        octant_idx = 0
        for ax in range(3):
            if breach_positive[ax]:
                bit = 0
            elif breach_negative[ax]:
                bit = 1
            else:
                bit = 1
            octant_idx |= (bit << ax)

        super_root.children[octant_idx] = old_root
        old_root.parent = super_root

        # Tile the newly added region with live leaves so the expanded space
        # actually accumulates heat. (Only leaves subdivide, so a child slot
        # left as None could never be populated — the whole expansion used to
        # be dead space.) Per axis the new bounds split into up to three
        # segments (below-old / old / above-old); every segment combination
        # except the all-old one is a non-overlapping extension box. Traversal
        # walks children by their own bounds (not octant arithmetic), so extra
        # children beyond the 8 octant slots are fine.
        def _segments(axis: int):
            segs = []
            if new_min[axis] < old_min[axis]:
                segs.append((new_min[axis], old_min[axis], False))
            segs.append((old_min[axis], old_max[axis], True))
            if new_max[axis] > old_max[axis]:
                segs.append((old_max[axis], new_max[axis], False))
            return segs

        for sx in _segments(0):
            for sy in _segments(1):
                for sz in _segments(2):
                    if sx[2] and sy[2] and sz[2]:
                        continue  # the old root's region
                    ext_leaf = OctreeNode(
                        bounds_min=np.array([sx[0], sy[0], sz[0]]),
                        bounds_max=np.array([sx[1], sy[1], sz[1]]),
                        level=old_root.level,
                        parent=super_root,
                    )
                    placed = False
                    for slot in range(8):
                        if super_root.children[slot] is None:
                            super_root.children[slot] = ext_leaf
                            placed = True
                            break
                    if not placed:
                        super_root.children.append(ext_leaf)
                    self._active_leaves.add(ext_leaf)

        self._root = super_root

    # ------------------------------------------------------------------ #
    # Detection extraction                                               #
    # ------------------------------------------------------------------ #
    def get_hot_voxels(self, threshold: Optional[float] = None) -> List[HotVoxel]:
        """Return active leaves with heat >= threshold, hottest first."""
        threshold = threshold if threshold is not None else self.config.hot_threshold
        results = [
            HotVoxel(heat=leaf.heat, center=leaf.center,
                     level=leaf.level, size_m=float(leaf.size[0]))
            for leaf in self._active_leaves
            if leaf.heat >= threshold
        ]
        results.sort(key=lambda v: v.heat, reverse=True)
        return results

    def cluster_hot_voxels(
        self,
        hot_voxels: List[HotVoxel],
        cluster_radius: float = 3.0,
    ) -> List[np.ndarray]:
        """Cluster nearby hot voxels into weighted detection centroids."""
        if not hot_voxels:
            return []

        clusters = []
        used = [False] * len(hot_voxels)

        for i, voxel in enumerate(hot_voxels):
            if used[i]:
                continue

            cluster_positions = [voxel.center]
            cluster_weights = [voxel.heat]
            used[i] = True

            for j, other in enumerate(hot_voxels[i + 1:], i + 1):
                if used[j]:
                    continue
                dist = np.linalg.norm(voxel.center - other.center)
                if dist <= cluster_radius:
                    cluster_positions.append(other.center)
                    cluster_weights.append(other.heat)
                    used[j] = True

            weights = np.array(cluster_weights)
            positions = np.array(cluster_positions)
            centroid = np.average(positions, axis=0, weights=weights)
            clusters.append(centroid)

        return clusters

    def get_detections(
        self,
        threshold: Optional[float] = None,
        cluster_radius: float = 3.0,
    ) -> List[np.ndarray]:
        """Get detection centroid positions from current grid state."""
        hot = self.get_hot_voxels(threshold)
        return self.cluster_hot_voxels(hot, cluster_radius)

    def get_stats(self) -> dict:
        """Get grid statistics (octree-aware)."""
        leaves = self._active_leaves
        n = len(leaves)
        return {
            'dimensions': (self.nx, self.ny, self.nz),       # kept for compat
            'total_voxels': n,                               # now: active leaf count
            'max_resolution_total_voxels': self.nx * self.ny * self.nz,
            'active_leaves': n,
            'max_heat': max((l.heat for l in leaves), default=0.0),
            'mean_heat': (sum(l.heat for l in leaves) / n) if n else 0.0,
            'hot_count': sum(1 for l in leaves if l.heat >= self.config.hot_threshold),
        }
