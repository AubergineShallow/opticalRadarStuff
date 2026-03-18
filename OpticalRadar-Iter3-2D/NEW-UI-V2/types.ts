/**
 * OpticalRadar Data Types
 * Closely matching backend implementation conventions.
 */

// Coordinate System: ENU (East-North) in Meters
// Vector2: [x, y] or [East, North]
export type Vector2 = [number, number];

// Legacy Vector3 for compatibility if needed, but z is ignored/0.
export type Vector3 = [number, number, number];

// Motion Vector: Lightweight vector from edge node
export interface MotionVector {
    azimuth_deg: number;   // [0, 360) - Clockwise from North
    intensity: number;     // [0, 255]
    timestamp: number;     // Unix float (GPS Time)
}

// Ray: Visual representation of a MotionVector in 2D space
export interface Ray {
    origin: Vector2;       // Camera position (ENU)
    direction: Vector2;    // Normalized direction vector (2D)
    intensity: number;     // [0, 255]
    camera_id: string;
    timestamp: number;
}

// Voxel: 2D Grid Cell (formerly Voxel)
export interface Voxel {
    x: number; // ENU Center X (Meters)
    y: number; // ENU Center Y (Meters)
    intensity: number; // [0, 255]
    timestamp: number;
}

export enum TrackState {
    TENTATIVE = 0,
    CONFIRMED = 1,
    LOST = 2,
    DELETED = 3,
}

export interface Track {
    track_id: number;
    state: TrackState;
    position: Vector2;      // ENU [East, North]
    velocity: Vector2;      // m/s [vE, vN]
    covariance: number[][]; // 2x2 or 4x4 matrix depending on filter
    first_seen: number;     // Unix timestamp
    last_seen: number;      // Unix timestamp
    hit_count: number;
    confidence: number;     // [0.0, 1.0]
    predicted_next: Vector2; // Position at t+dt
    history?: Vector2[];    // Array of past positions
}

export enum NodeHealthStatus {
    HEALTHY = 0,
    DEGRADED = 1,
    FAILING = 2,
    OFFLINE = 3,
}

export interface NodeHealth {
    node_id: string;
    status: NodeHealthStatus;
    last_seen: number;     // Unix timestamp
    fps: number;
    cpu_usage: number;     // Percentage [0, 100]
    temp_c: number;        // Celsius
    ip_address: string;
    location: Vector2;     // ENU [East, North]
    mode: number;          // 0: tracking, 1: stream
    // Configuration for Visualization
    config?: {
        azimuth_deg: number; // Degrees clockwise from North
        fov_deg: number;
        range_meters: number;
    };
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