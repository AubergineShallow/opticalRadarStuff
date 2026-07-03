# Architecture and System Design

## Overview
This document outlines the high-level architecture and design principles of the Optical Radar project. The system implements multi-domain tracking via the `ClusterManager` and integrates an array of edge nodes (Raspberry Pi, Android, ESP32) that communicate with a central server backend.

## Ontology and Standards
The project incorporates the **Distributed Optical Passive Tracking (DOPT) Networks specification**. Its core semantic ontology extends SOSA/SSN (Sensor, Observation, Sample, and Actuator) and is defined in `ontology/dopt.ttl`.

## Core System Architecture
The system consists of a central backend and distributed edge nodes communicating over secure UDP/WebSocket channels, with fallback to LoRa/Meshtastic networks.

### Multi-Domain Tracking
- Managed centrally by the `ClusterManager`.
- Employs vectorized data association and Kalman Filter operations for performance.
- Incorporates a continuous calibration feedback loop to adjust sensor biases dynamically.

### Object Size Estimation Model
- **Edge Nodes:** Calculate an object's angular size, conceptualized mathematically as a projective circular cone based on the camera's intrinsic parameters.
- **Server:** Correlates detections from multiple nodes to triangulate the instantaneous distance. This distance is then combined with the angular size to estimate the physical dimensions of the object in 3D space.

## Edge Nodes

### Raspberry Pi Node (`code/rpi/`)
- Exposes a consolidated public API through `__init__.py`, re-exporting classes like `VisionSystem`, `GPSReader`, `IMUReader`, and `RPiNode`.
- **Simulation Mode:** Features a mock/simulation mode (in `code/rpi/sensors.py`) that bypasses physical hardware checks (GPIO/OpenCV cameras) and generates simulated sensor data, facilitating testing in headless or restricted environments.

### Android Node
- Implemented as a foreground service (`RadarService.kt`), carefully configured to comply with Android 14 foreground-service restrictions.
- **IMU Orientation:** Uses `SensorManager.getQuaternionFromVector` to extract quaternions from the hardware rotation vector sensor. The data is transmitted in `[w, x, y, z]` format to align with the backend's ENU (East-North-Up) coordinate convention.
- **Location:** Integrates real hardware GPS via the `FusedLocationProviderClient`.

### ESP32-CAM Node
- Supported via custom firmware. Typically serves as a low-cost, low-power edge detection component.
- Integrates with LoRa/Meshtastic networks for deployment in areas with degraded communication infrastructure.

## Backend Server Execution
The backend server provides a few entry points for flexibility:
- Can be run natively as a module: `python -m server.server_main`
- Can be launched via the provided wrapper script: `python run_server.py`