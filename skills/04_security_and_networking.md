# Security and Networking

## Security Module

The security layer establishes a zero-trust model between edge nodes and the backend server.

### Key Management (`code/server/security/key_manager.py`)
- **Key Distribution:** To prevent command injection and SSH option injection vulnerabilities in `KeyManager.distribute_key_ssh` and `KeyManager.verify_sync`, user-controlled strings MUST be sanitized:
  - Interpolated variables into remote shell strings must be escaped using `shlex.quote`.
  - `subprocess.run` calls must use array format specifically structured to avoid option injection: `['ssh', '-l', username, '--', host, command]`.
- **Loading Keys:** The `_load_from_defaults` method catches all exceptions during its execution loop to safely fall back to subsequent key locations, failing entirely only if no secure, valid key can be located.
- **POSIX Permissions:** Security-critical key file permission checks (enforcing `0o600` permissions) in `Authenticator` and `KeyManager` are gated with `os.name == 'posix'` to prevent crashes on Windows environments while ensuring strict compliance on Linux and macOS.

### Packet Authentication
- **Dynamic Validation:** `Authenticator` dynamic signature validation ensures packets are trusted. It verifies that incoming packet lengths are $\ge$ `HEADER_SIZE + SIGNATURE_SIZE` and validates signatures against `KeyManager.all_valid_keys`.

## Networking

### Distributed Network Utilities
- **Centralized UDP:** Standardized network routines, such as transmitting secure UDP packets, are implemented centrally in `code/common/network.py` and exported through the `code/common/` namespace. This prevents fragmentation across node types and simulation code.

### WebSockets (`code/server/websocket_server.py`)
- **Room-based Routing:** The `WebSocketBroadcaster` partitions data globally using a room-based routing mechanism keyed by `cluster_id` (e.g., `broadcast_tracks(..., room=cluster_id)`).
- **Command Handling:** Maintains a robust command handler registry (`register_command_handler`) to listen for operations from connected clients.

### 3D Foxglove Streaming
- **Integration:** The backend supports Foxglove streaming using `FoxgloveBroadcaster`, enabling real-time 3D introspection via the `foxglove-sdk`. The dependency list is maintained independently in `code/requirements-foxglove.txt`.
- **Ghost Geometry Prevention:** Because Foxglove Studio 3D panels do not explicitly track per-ID deletion for scenes without custom plugins, `SceneUpdate` entities published by the Optical Radar server are intentionally assigned short lifetimes (e.g., ~66ms) to self-clear naturally.