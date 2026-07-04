/**
 * OpticalRadar Data Types
 * Closely matching backend implementation conventions.
 */

// Coordinate System: ENU (East-North-Up) in Meters
// Vector3: [x, y, z] or [East, North, Up]
export type Vector3 = [number, number, number];

// Motion Vector: Lightweight vector from edge node
export interface MotionVector {
    azimuth_deg: number;   // [0, 360) - Clockwise from North
    elevation_deg: number; // [-90, 90] - Positive Up
    intensity: number;     // [0, 255]
    timestamp: number;     // Unix float (GPS Time)
}

// Ray: Visual representation of a MotionVector in 3D space
export interface Ray {
    origin: Vector3;       // Camera position (ENU)
    direction: Vector3;    // Normalized direction vector
    intensity: number;     // [0, 255]
    camera_id: string;
    timestamp: number;
    cluster_id?: string;   // owning cluster (stamped by backend, P0.6)
}

// Voxel: 3D Grid Unit
export interface Voxel {
    x: number; // ENU Center X (Meters)
    y: number; // ENU Center Y (Meters)
    z: number; // ENU Center Z (Meters)
    intensity: number; // [0, 255]
    timestamp: number;
    cluster_id?: string;  // owning cluster (stamped by backend, P0.6)
}

export enum TrackState {
    TENTATIVE = 0,
    CONFIRMED = 1,
    LOST = 2,
    DELETED = 3,
}

// Precomputed display fields (P3.2) — derived once at WebSocket receipt instead
// of inside every table render. ENU-derived lat/lon are display approximations,
// NOT for geodetic targeting.
export interface TrackDisplayProps {
    speed_ms: number;     // sqrt(vE^2 + vN^2 + vU^2)
    heading_deg: number;  // atan2(vE, vN) normalised to [0, 360)
    lat: number;          // ENU-derived approximation
    lon: number;
}

export interface Track {
    track_id: number;
    state: TrackState;
    position: Vector3;      // ENU [East, North, Up]
    velocity: Vector3;      // m/s [vE, vN, vU]
    covariance: number[][]; // 3x3 matrix
    first_seen: number;     // Unix timestamp
    last_seen: number;      // Unix timestamp
    hit_count: number;
    confidence: number;     // [0.0, 1.0]
    predicted_next: Vector3; // Position at t+dt
    cluster_id?: string;     // owning cluster (stamped by backend, P0.6)
    // EMA-smoothed physical size estimate in metres, fused server-side from the
    // angular sizes reported by the sensors (2*range*tan(theta/2), median over
    // nodes). 0 / absent = no estimate available.
    physical_size?: number;
    display?: TrackDisplayProps; // precomputed at receipt (P3.2)
}

export enum NodeHealthStatus {
    HEALTHY = 0,
    DEGRADED = 1,
    FAILING = 2,
    OFFLINE = 3,
}

export interface SensorConfig {
    azimuth_deg: number;
    elevation_deg: number;
    hfov_deg: number;
    vfov_deg: number;
}

export interface NodeHealth {
    node_id: string;
    status: NodeHealthStatus;
    last_seen: number;     // Unix timestamp
    fps: number;
    cpu_usage: number;     // Percentage [0, 100]
    temp_c: number;        // Celsius
    ip_address: string;
    location: Vector3;     // ENU
    sensor_config?: SensorConfig; // optional — backend may not always send it (P3.1)
    cluster_id?: string;          // owning cluster (P0.6)
    display_lat?: number;         // ENU-derived approximation, precomputed (P3.2)
    display_lon?: number;
}

// Cluster / domain topology (P3.5)
export interface ClusterInfo {
    cluster_id: string;
    node_ids: string[];
    track_count: number;
    voxel_resolution_m: number;
}

export interface SystemStatus {
    server_fps: number;
    total_tracks: number;
    total_voxels: number;
    uptime_seconds: number;
    cpu_percent: number;
    memory_percent: number;
}

export interface WSMessage {
    type: 'TRACK_UPDATE' | 'VOXEL_UPDATE' | 'RAY_UPDATE' | 'NODE_UPDATE'
        | 'SYSTEM_STATUS' | 'CLUSTER_UPDATE';
    payload: any;
}
