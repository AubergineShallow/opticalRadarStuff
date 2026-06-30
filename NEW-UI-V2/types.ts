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
}

// Voxel: 3D Grid Unit
export interface Voxel {
    x: number; // ENU Center X (Meters)
    y: number; // ENU Center Y (Meters)
    z: number; // ENU Center Z (Meters)
    intensity: number; // [0, 255]
    timestamp: number;
}

export enum TrackState {
    TENTATIVE = 0,
    CONFIRMED = 1,
    LOST = 2,
    DELETED = 3,
}

export interface TrackDisplayProps {
    speed_ms:   number;     // √(vE²+vN²+vU²)
    heading_deg: number;    // atan2(vE, vN) normalised [0, 360)
    lat:         number;    // ENU-derived approximation (not for geodetic targeting)
    lon:         number;
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
    display?: TrackDisplayProps;
}

export enum NodeHealthStatus {
    HEALTHY = 0,
    DEGRADED = 1,
    FAILING = 2,
    OFFLINE = 3,
}

export interface SensorConfig {
    azimuth_deg:   number;
    elevation_deg: number;
    hfov_deg:      number;
    vfov_deg:      number;
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
    sensor_config?: SensorConfig;  // optional - backend may not always send it
    display_lat?: number;
    display_lon?: number;
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
    type: 'TRACK_UPDATE' | 'VOXEL_UPDATE' | 'RAY_UPDATE' | 'NODE_UPDATE' | 'SYSTEM_STATUS';
    payload: any;
}