# Non-UI Code Scan Report

## Unused Imports & Variables
A significant amount of technical debt remains in the form of unused imports (F401) and assigned but unused local variables (F841) across many files. Notable ones include:
- `code/common/protocol.py`: Unused `numpy as np`
- `code/esp32/esp32_stub.py`: Unused `typing.Tuple`
- `code/math_utils/geo.py`: Unused `numpy as np`
- `code/math_utils/quaternion.py`: Unused `numpy as np`
- `code/server/monitoring/node_health.py`: Unused local variable `imu_ok`
- `code/server/server_main.py`: Unused `Config`, `get_logger`, `typing.List`
- `code/system_test.py`: Unused `threading`, local variables `tracks`, `detections`, and multiple protocol imports.
- Various `typing` module imports (`List`, `Tuple`, `Optional`, `Callable`, `Dict`) are unused across `native_wrapper.py`, `vision.py`, `udp_server.py`, `calibration_validator.py`, `websocket_server.py`, etc.
- Unused `dataclasses.field` in `calibration.py`, `node_health.py`, `track_manager.py`, `ground_truth.py`.
- `code/server/monitoring/logger.py`: Standard `logging` is imported but unused (as noted in memory, this is a custom implementation).

## Code Style / Linting (PEP 8)
- Many files have `E501` (Line too long) and `W293` (Blank line contains whitespace) violations. Most heavily impacted are `code/simulation/sim_node.py` and `code/system_test.py`.

## Security & Concurrency
- `code/server/security/key_manager.py`: Implements strict 0o600 permissions, which is a positive.
- `code/server/server_main.py`: Has fail-open authentication on `PermissionError`, which is known but is a potential security risk if the environment allows missing/insecure keys to completely bypass authentication.
