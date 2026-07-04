---
name: geometry-conventions
description: The coordinate frames, angle conventions, quaternion format, and unit transitions used across OpticalRadar — WGS84↔ECEF↔ENU conversions, the shared ENU reference origin, quaternion [w,x,y,z] ZYX-Euler conventions, wrap180, and the per-layer units table. Read before touching any math that crosses a module boundary.
---

# Geometry & Units Conventions

Cross-module math bugs (wrong frame, wrong unit, wrong quaternion order) are this
project's most expensive class of bug — several shipped historically. This is
the contract.

## Coordinate frames

```
WGS84 (lat°, lon°, alt m)  ←GPS fixes on the wire
  ↕ math_utils/geo.py
ECEF (X, Y, Z m)           ←intermediate only
  ↕
ENU (east, north, up m)    ←ALL server-side geometry: rays, voxels, tracks, UI
```

`math_utils/geo.py` (pure functions, WGS84 ellipsoid constants `WGS84_A/B/E2`):
`wgs84_to_ecef`, `ecef_to_enu(x,y,z, ref_lat,ref_lon,ref_alt)`,
`wgs84_to_enu(lat,lon,alt, ref...)`, `enu_to_wgs84(e,n,u, ref...)` (iterative
`ecef_to_wgs84` inside), plus `haversine_distance`, `calculate_look_angles`.
Altitude is height above the WGS84 **ellipsoid** (matches GPS), not MSL.

Verified round-trip example (from `code\`):

```bash
python -c "
from math_utils.geo import wgs84_to_enu, enu_to_wgs84
e, n, u = wgs84_to_enu(37.7758, -122.4180, 25.0, 37.7749, -122.4194, 0.0)
print(f'ENU: e={e:.3f} n={n:.3f} u={u:.3f}')
print('back:', enu_to_wgs84(e, n, u, 37.7749, -122.4194, 0.0))
"
# ENU: e=123.339 n=99.894 u=24.998
# back: (37.7758, -122.418, 25.0)   (to 7 decimals)
```

## The ENU reference origin — one origin to rule them all

THREE places must agree on the origin or nothing tracks:

1. Server: `reference.origin_lat/lon/alt` in `common/config.py::ReferenceConfig`
   (default 37.7749, −122.4194, 0 — San Francisco), consumed by each cluster's
   RayBuilder.
2. Frontend: `COORDINATE_ORIGIN` in `NEW-UI-V2/constants.ts` — the map overlay
   renders ENU positions relative to it.
3. Data: nodes' actual GPS fixes (and `simulation/sim_node.py::
   create_demo_simulation`'s hardcoded ref) must be NEAR that origin — the grid
   is only ~200 m wide.

History: a (0,0,0) default origin once put every realistic GPS node thousands of
km outside the voxel grid, so nothing was ever tracked. If tracks are absent and
node ENU positions are huge, check the origin first (silent-drop checklist row 5
in `run-and-debug-server`). When deploying to a new site, change all of (1), (2)
and confirm (3).

## Quaternions (`math_utils/quaternion.py`)

- **Component order `[w, x, y, z]`** — everywhere: the wire format
  (`TelemetryPacket.orientation`), rpi/Android/firmware senders, `rotate_vector`.
  scipy uses `[x, y, z, w]`; convert explicitly if you ever bridge them.
- Hamilton convention; `rotate_vector(v, q)` applies the ACTIVE rotation q·v·q*
  (body-frame direction → world/ENU direction given the node's orientation).
- `from_euler(roll, pitch, yaw)` — **degrees**, ZYX (yaw-pitch-roll) convention,
  roll=X, pitch=Y, yaw=Z; returns normalized [w,x,y,z]. Periodic in 360° as a
  ROTATION: `from_euler(0,0,330)` is `-1 ×` `from_euler(0,0,-30)` — q and −q
  rotate identically (`rotate_vector` agrees), which is what makes wrap180
  lossless on the LoRa path; but the tuples are NOT `==`, don't compare them
  directly. `to_euler` inverts (ZYX).
- Identity is `(1.0, 0.0, 0.0, 0.0)`.
- **Zero/NaN quaternions**: rejected at server ingest
  (`server_main._telemetry_sane`, |q|² < 1e-12), and `RayBuilder.build_ray`
  additionally drops rays whose rotated direction is degenerate. Preserve both
  layers — struct.unpack happily produces NaN floats.

## Bearing convention

Azimuth/elevation everywhere (MotionVector, LoRa UPDATE, vision code):
**azimuth 0° = North, 90° = East (clockwise from north); elevation 0° = horizon,
positive up**. Camera-RELATIVE (body frame): `RayBuilder.angles_to_direction`
makes unit [E,N,U] in the body frame, then the node quaternion world-rotates it.
Detectors (rpi `vision.py`, Android `VisionAnalyzer.kt`, firmware `detector.cpp`)
map pixel offsets to these bearings via rectilinear projection with the node's
FOV — sourced from `config/node_specs.json` (RPi), `include/config.h` kept in
sync with that file (firmware), or queried live from `CameraCharacteristics`
(Android).

## wrap180

`common/lora_protocol.py::wrap180(angle) → [-180, 180)`. MUST be applied before
any int16-centidegree encoding (LoRa ANNOUNCE roll/pitch/yaw): int16 centidegrees
spans only ±327.67°, so a 0–360 heading overflows above 327.67. Wrapping is
lossless because the consumer is periodic `from_euler`. The C++ firmware mirrors
it (`lora_protocol.h::wrap180`). See `wire-protocols` invariants.

## Units by layer

| Layer | Angle units | Position units |
|---|---|---|
| Detector pixel math (vision.py / VisionAnalyzer / detector.cpp) | pixels → degrees (via FOV) | pixels |
| V3 MotionVector wire | scaled uint16/int16 (az /360, el /90, size /180 — see `wire-protocols`) | — |
| LoRa ANNOUNCE wire | int16 **centi**degrees (pose), float32 lat/lon/alt | WGS84 |
| LoRa UPDATE wire | uint16 az, int8 whole-degree el, uint8 size | — |
| Python protocol objects | degrees (floats) | WGS84 degrees + meters alt |
| RayBuilder internals | radians (`np.radians` at the boundary) | ENU meters |
| VoxelGrid / Tracker / broadcasts | — | ENU meters |
| UI (NEW-UI-V2) | degrees for display | ENU meters, mapped via COORDINATE_ORIGIN |

Rule: **degrees on wires and APIs, radians only inside a function's local math.**
Every function that takes radians converts at its own boundary.

## Pitfalls

- int16 centidegrees clamp at ±327.67° — clamping is a *safety net*; correctness
  comes from wrap180 first.
- Quantization TRUNCATES toward zero on both language sides — never round
  (`wire-protocols` invariant 1).
- Elevation int8 on LoRa UPDATE is WHOLE degrees (resolution 1°) — don't expect
  sub-degree elevation over LoRa.
- `enu_to_wgs84` is iterative — fine for per-node rates, don't put it in a
  per-ray inner loop.
- ENU is a local tangent frame: beyond ~10 km from origin, curvature error grows.
  The 200 m default grid is far inside safe range; a much larger deployment needs
  thought.

## Related skills

`wire-protocols` (encodings), `tracking-fusion` (consumers of these frames),
`run-and-debug-server` (origin misconfig symptoms).
