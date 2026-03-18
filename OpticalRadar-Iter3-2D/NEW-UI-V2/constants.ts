import { NodeHealthStatus } from "./types";

export const ROOM_CONFIG = {
    WIDTH: 20,  // Meters (X axis) - doubled
    DEPTH: 16,   // Meters (Y axis) - doubled
};

export const UI_CONFIG = {
    // Center the view on 0,0 (Middle of room)
    INITIAL_VIEW_STATE: {
        latitude: 0,
        longitude: 0,
        zoom: 20.5, // Zoom out to fit the larger room (was 22)
        pitch: 0,
        bearing: 0
    },
    // Reference Origin for ENU conversions.
    // We treat 0,0 as the center of the room.
    // This lat/lon is arbitrary but ensures DeckGL math works.
    COORDINATE_ORIGIN: [0, 0, 0] as [number, number, number],

    // Visualization Settings (Scaled for Indoor)
    RAY_LENGTH_METERS: 25, // Increased for larger room
    VOXEL_SIZE_METERS: 0.25, // 25cm grid
    TRACK_POINT_RADIUS: 0.3, // ~30cm radius (avg human shoulder width)
    NODE_POINT_RADIUS: 0.15, // Small camera node

    // Colors [R, G, B, A]
    COLORS: {
        NODE_HEALTHY: [0, 255, 65] as [number, number, number],
        NODE_ISSUE: [255, 0, 0] as [number, number, number],
        RAY_DEFAULT: [0, 255, 255, 30] as [number, number, number, number],
        TRACK_DEFAULT: [255, 100, 50] as [number, number, number], // Orange for people
        TEXT_LABEL: [255, 255, 255] as [number, number, number],
        ROOM_FLOOR: [20, 20, 25] as [number, number, number],
        ROOM_GRID: [50, 50, 60] as [number, number, number],
        ROOM_WALLS: [100, 100, 100] as [number, number, number],
    }
};

export const Env = {
    // Default to localhost:5000/ws for WebSocket
    WS_URL: 'ws://localhost:5000/ws',
    // Check URL param ?mock=true
    ENABLE_MOCK_DATA: false
};

export const STATUS_COLORS = {
    [NodeHealthStatus.HEALTHY]: "text-green-500",
    [NodeHealthStatus.DEGRADED]: "text-yellow-500",
    [NodeHealthStatus.FAILING]: "text-orange-500",
    [NodeHealthStatus.OFFLINE]: "text-red-500",
};