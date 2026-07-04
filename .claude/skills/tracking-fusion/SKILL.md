---
name: tracking-fusion
description: Understand, tune, or extend the core fusion pipeline — sparse octree voxel grid, ray building, measurement covariance from node optics, Kalman tracking and data association, cluster/domain management, self-calibration, and physical-size estimation. Includes the tuning-knobs table and the invariants that keep the 30 Hz loop real-time.
---

# Tracking & Fusion Core

Bearing-only sensors → 3D tracks. The chain per frame (see `run-and-debug-server`
for the surrounding loop):

```
telemetry → RayBuilder (bearings→world rays) → VoxelGrid (heat accumulation,
octree subdivision) → get_detections (hot-voxel centroids) → Detection objects
(+ covariance from uncertainty.py, + size sample) → Tracker (associate → Kalman
update → lifecycle) → TRACK_UPDATE broadcast
```

Everything is **per cluster**: `server/cluster_manager.py::Cluster` bundles one
`ray_builder + voxel_grid + tracker`. `ClusterManager` caps clusters at
`network.max_clusters` (64; `create_cluster` returns None at cap — callers must
handle it); the `DEFAULT` cluster always exists; announced nodes auto-assign to
DEFAULT.

## RayBuilder (`server/ray_builder.py`)

- `update_camera` converts the node's GPS fix to ENU against the shared reference
  origin (`reference.*` config) and stores a `CameraState`.
- `angles_to_direction(az, el)`: az 0°=North, 90°=East (clockwise from North);
  el 0°=horizon, +up. Returns unit [E, N, U] (see `geometry-conventions`).
- `build_ray`: body-frame direction → rotated by the node quaternion → rotated by
  the node's calibration offset (if any) → normalized. Degenerate rotations
  (near-zero norm) drop the ray rather than injecting NaN into the grid.
- GPS gating happens BEFORE ray building, in `server_main._process_packet`
  (health bit 0x01) — not here.

## VoxelGrid octree (`server/voxel_grid.py`)

Sparse octree, coarse-to-fine: starts as one root leaf; a leaf **subdivides only
when ≥ `min_cameras_to_subdivide` (3) DISTINCT cameras hit it within a
co-temporal window** (`camera_window_frames`=10, driven by the `frame_index`
passed from the main loop). This is the core multi-camera triangulation
mechanism — one camera alone can never concentrate heat, which is why
single-node setups produce no detections (see silent-drop checklist row 6 in
`run-and-debug-server`).

- Traversal: stack-based coarse-to-fine octree descent with ray–AABB slab tests
  (`_traverse_octree`, `_ray_slab`); each intersected leaf deposits heat exactly
  once, scaled by intensity. (NOT Amanatides–Woo DDA — no per-voxel stepping;
  older docs that say A–W are stale.)
- Per-frame `decay_active_leaves()` (heat × `decay_rate` 0.95) is decoupled from
  throttled `consolidate_and_prune()` (collapse leaves below `cold_threshold`
  0.5; runs every ≥1.5 s from the main loop) — do not re-merge them; heat must
  fade at the configured per-frame rate.
- **THE perf guard**: `max_active_leaves` (20000, config `grid.max_active_leaves`).
  Subdivision is per-ray with no intrinsic bound; an adversarial/noisy scene once
  drove the tree to 500k+ leaves collapsing ingest to ~10 pkts/s. At the cap the
  grid stops refining and deposits into the coarse leaf — graceful accuracy
  degradation, loop stays real-time. Stress S6 covers this. Never remove or
  bypass the cap.
- `expand_root` grows the world when a ray breaches the configured volume;
  coordinates of existing leaves are preserved.
- Output: `get_hot_voxels` (heat ≥ `hot_threshold` 5.0) → `cluster_hot_voxels` →
  `get_detections` yields centroid ndarrays.

Note there are TWO config classes: `VoxelGridConfig` (in voxel_grid.py, full) and
`GridConfig` (in common/config.py, the YAML-facing subset). `Cluster.__init__`
maps GridConfig→VoxelGridConfig; when adding a knob add it to BOTH and wire the
mapping (a `hot_threshold`/`decay_rate` wiring gap is exactly what system_test
Phase 12 regression-guards).

## Measurement covariance (`server/uncertainty.py`)

`measurement_covariance(position, [(cam_pos, sigma_theta), ...])` fuses per-node
bearing uncertainty into a 3×3 positional R in information form: each node
contributes tight cross-range (`rho·sigma_theta`, floored at `min_cross_range` =
grid resolution) and loose along-ray (`sigma_range`=100 m) information. One node
⇒ long thin depth-uncertain ellipsoid; two well-separated nodes ⇒ compact R.
Distant nodes self-attenuate — no visibility gate needed
(though `measurement_covariance` does hard-skip nodes beyond `max_range` 500 m). `sigma_theta` per node
comes from announced/file-provisioned optics (`common/node_specs.py`,
`server_main._node_sigma_theta`). R rides on each `Detection` and the Kalman
update weights it per-measurement (system_test Phase 15).

## Tracker stack (`server/tracking/`)

- `kalman_filter.py`: constant-velocity model, state `[x,y,z,vx,vy,vz]`,
  measurement `[x,y,z]`; accepts per-measurement R.
- `data_association.py`: cost matrix on distance; `associate(..., use_hungarian=True)`
  (Hungarian via scipy — **this is why the server needs scipy**), greedy fallback;
  gate `max_distance` = `tracking.distance_threshold_m` (5.0).
- `track_manager.py`: lifecycle TENTATIVE(0) → CONFIRMED(1) (after
  `tracking.min_hits_to_confirm`=3) → LOST(2) (after `misses_to_lost`=5
  consecutive misses — a TrackManager arg, not a YAML key) → DELETED(3) (after
  `tracking.max_misses_to_delete`=30 total misses). Wire states in
  `common/constants.py::TRACK_STATE_*` must stay in sync with the UI.
  Physical-size smoothing lives here: `SIZE_EMA_ALPHA = 0.2`; first sample seeds
  directly; sizeless detections KEEP the estimate (never zero it).
- `tracker.py`: orchestrates predict→associate→update→lifecycle; `Detection`
  dataclass carries `position`, optional `covariance`, optional `size_estimate`.

## Physical-size estimation (`server_main.py::_estimate_physical_size`)

Design (landed 2026-07-03): fusion happens at detection-build time
(`_build_detections`) reusing `_pending_rays` — the frame's rays are still
buffered for the RAY_UPDATE broadcast at that point, so no extra bookkeeping.
Per candidate ray: reject `angular_size` ≤0 or ≥90° (detector artefact; tan
explodes), range > `_size_max_range` (500 m), behind-camera (along ≤ 0), and
rays whose perpendicular miss distance exceeds `target_radius + 2×grid
resolution` (`_size_match_slack_m`). Contribution: `2·rho·tan(theta/2)`; median
across sensors; None ⇒ track keeps previous EMA. Verified by system_test
Phase 17.

**Known cost**: this is O(detections × rays) pure Python per frame and is the
prime suspect for the stress S8 throughput failure (see `validate-changes`).
If you optimize it, keep Phase 17 semantics intact.

## Self-calibration (`server/calibration.py` + `server/validation/`)

Feedback loop: rays near CONFIRMED tracks (hits ≥ `calibration.min_track_hits`,
within `association_radius_m` 10 m) become observations
(`server_main._collect_calibration_observations`); every `solve_interval` (10 s)
the Calibrator solves per-node orientation offsets, `CalibrationValidator` gates
them (`max_correction_degrees` 15, `min_observations` 100); approved offsets go
into the node's RayBuilder and persist to `calibration.offsets_file`
(`secrets/calibration_offsets.json`), reapplied on restart
(`_ensure_calibration_offset`). Per-node status
(uncalibrated/converging/converged/diverged) is broadcast in SYSTEM_STATUS and
shown in the UI. `validation/ground_truth.py::GroundTruthValidator` compares the
best track against GT packets (type 0x03) for accuracy evaluation.
NOTE (deferred item): the solve runs synchronously ON the 30 Hz loop thread —
long solves can stutter the loop; see `quality-standards`.

## Tuning knobs

| Knob (config) | Default | Effect / when to touch |
|---|---|---|
| `grid.resolution_m` | 1.0 | finest leaf size; also floors cross-range sigma and scales the size-match slack |
| `grid.decay_rate` | 0.95 | heat memory; lower = faster fade, fewer stale voxels |
| `grid.hot_threshold` | 5.0 | detection sensitivity; raise if noise voxels become detections |
| `grid.max_active_leaves` | 20000 | perf ceiling; raise only with profiling evidence |
| `grid.width_m/depth_m/height_m` | 200/200/100 | tracked volume (root auto-expands on breach) |
| `VoxelGridConfig.min_cameras_to_subdivide` | 3 | lower to 2 for 2-camera rigs, else nothing ever subdivides. **Not a `grid.*` YAML key** — a YAML entry is warned-and-ignored; set in code / extend the Cluster mapping |
| `VoxelGridConfig.camera_window_frames` | 10 | co-temporal window for the M-camera trigger (also not a YAML key) |
| `tracking.distance_threshold_m` | 5.0 | association gate; scale with target speed / frame rate |
| `tracking.min_hits_to_confirm` | 3 | confirmation latency vs false tracks |
| `tracking.max_misses_to_delete` | 30 | track persistence through occlusion (~1 s at 30 fps) |
| `tracking.q_process_noise` / `r_measurement_noise` | 0.1 / 2.0 | Kalman defaults (R overridden per-measurement when optics known) |
| `calibration.*` | see config.py | solver cadence/gates (above) |
| `server.target_fps` | 30 | loop rate — everything per-frame scales with it |

## Related skills

`geometry-conventions` (frames/units feeding this), `run-and-debug-server` (loop
+ silent drops), `validate-changes` (Phases 4/6/11/15/17, stress S6),
`quality-standards` (caps philosophy, deferred items).
