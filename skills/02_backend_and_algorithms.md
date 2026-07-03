# Backend and Algorithms

## Voxel Grid Pipeline

The 3D space is modeled using a Hierarchical Octree architecture managed within `code/server/voxel_grid.py`.

### Octree Operations
- **Heat Decay:** The voxel grid applies a heat decay mechanism (`decay_active_leaves`) to age out older detections. This process executes every frame at a rate of 30Hz.
- **Housekeeping:** Structural consolidation and pruning of the octree (`consolidate_and_prune`) is throttled to a 1.5-second cadence to balance performance and memory usage.
- **Node Identification:** To store nodes effectively in the `_active_leaves` set, the `OctreeNode` class implements a custom `__hash__` method returning `id(self)` and sets `eq=False`.
- **Retrieval Optimization:** The `get_hot_voxels` method utilizes `heapq.nlargest` alongside a generator expression to efficiently return the top/hottest voxels, resulting in ~60% faster retrieval (e.g., when requesting the top 100 voxels).
- **Clustering:** The `cluster_hot_voxels` method iterates over hot voxels using `range`-based indexing instead of list slicing, avoiding $O(N)$ memory copies and yielding a ~7% speedup.
- **Configuration:** The heat threshold property in `VoxelGridConfig` is `hot_threshold` (default 5.0, replacing the deprecated `detection_threshold`). The `decay_rate` default is 0.95.

### Ray Traversal
- **Amanatides-Woo Algorithm:** Ray intersection and traversal through the octree are handled exactly using the Amanatides-Woo algorithm (`_traverse_amanatides_woo`). This ensures exact cell-boundary stepping and eliminates the double-counting or skipping issues often associated with fixed-step marching.
- **Ray Data Structure:** The `Ray` object stores fields as attributes (`r.origin`, `r.direction`, `r.intensity`). Accessing them via list indexing (`r[0]`) causes unpacking errors.
- **Camera Lookup:** The server fetches a camera's position via `RayBuilder.get_camera_position(camera_id)` (`code/server/ray_builder.py`), which returns a `numpy.ndarray` containing the ENU coordinates or `None` if unrecognized.

## Tracking and Data Association

Located primarily in `code/server/tracking/data_association.py`.

### Assignment
- Matching incoming detections to existing tracks is solved as an assignment problem using the Hungarian algorithm via `scipy.optimize.linear_sum_assignment`.
- The cost matrices are computed based on either Euclidean distance or 3D Intersection over Union (IoU).

### 3D IoU Calculation
- The `iou_3d` implementation processes axis-aligned bounding boxes.
- It robustly handles edge cases, specifically verified via unit tests for: identity, zero overlap, partial overlap, containment, and degenerate (zero-volume) boxes.

### Tracker State Management
- `Tracker` instances maintain the state of tracked objects. Tracks are accessed using the `get_all_tracks()` method (there is no `get_active_tracks()` method).

## Coordinate Systems and Math

- **Quaternions:**
  - The function `to_axis_angle` in `code/math_utils/quaternion.py` canonicalizes quaternions by enforcing that $w \ge 0$ before extraction. This resolves the double-cover property of quaternions where $q$ and $-q$ represent the same rotation but would produce inverted rotation axes.
  - Quaternions are transmitted in `[w, x, y, z]` format across the system.
- **Geo-Math:**
  - WGS84 Reference Ellipsoid parameters are utilized in `code/math_utils/geo.py`:
    - `WGS84_A = 6378137.0` (semi-major axis)
    - `WGS84_B = 6356752.314245` (semi-minor axis)

## Protocols

### Optical Radar V3 Protocol
Defined in `code/common/protocol.py`.
- Incorporates security and sequence numbers.
- A `MotionVector` payload is packed tightly into 6 bytes:
  - Azimuth: `uint16`
  - Elevation: `int16`
  - Intensity: `uint8`
  - Class ID: `uint8`
- *Note:* The current protocol does **not** transmit angular size or bounding box dimensions within the `MotionVector` packet itself.
- **Telemetry:** The `TelemetryPacket` protocol does *not* contain a `battery_level` field. When broadcasting node status, the server must substitute `None` or omit it.