import { useEffect, useRef, useState } from 'react';
import { useAppStore } from './store';
import { Track, TrackState, NodeHealthStatus, Ray, WSMessage } from './types';
import { ROOM_CONFIG } from './constants';

/**
 * Hook to manage WebSocket connection to the Python backend.
 */
export function useWebSocket(url: string, enabled: boolean = true) {
    const {
        setTracks,
        setVoxels,
        setRays,
        updateNode,
        updateSystemStatus
    } = useAppStore();

    const [isConnected, setIsConnected] = useState(false);
    const wsRef = useRef<WebSocket | null>(null);

    useEffect(() => {
        if (!enabled) {
            return;
        }

        console.log(`[WebSocket] Connecting to ${url}...`);
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
            console.log('[WebSocket] Connected');
            setIsConnected(true);
        };

        ws.onclose = () => {
            console.log('[WebSocket] Disconnected');
            setIsConnected(false);
        };

        ws.onerror = (error) => {
            console.error('[WebSocket] Error:', error);
        };

        ws.onmessage = (event) => {
            try {
                const message: WSMessage = JSON.parse(event.data);

                switch (message.type) {
                    case 'TRACK_UPDATE':
                        setTracks(message.payload);
                        break;
                    case 'VOXEL_UPDATE':
                        setVoxels(message.payload);
                        break;
                    case 'RAY_UPDATE':
                        setRays(message.payload);
                        break;
                    case 'NODE_UPDATE':
                        if (Array.isArray(message.payload)) {
                            message.payload.forEach((node: any) => updateNode(node));
                        } else {
                            updateNode(message.payload);
                        }
                        break;
                    case 'SYSTEM_STATUS':
                        updateSystemStatus(message.payload);
                        break;
                    default:
                        console.warn('[WebSocket] Unknown message type:', (message as any).type);
                }
            } catch (err) {
                console.error('[WebSocket] Failed to parse message:', err);
            }
        };

        return () => {
            if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
                ws.close();
            }
        };
    }, [url, enabled, setTracks, setVoxels, setRays, updateNode, updateSystemStatus]);

    return { isConnected };
}

export function useMockData(enabled: boolean = true) {
    const { setTracks, updateSystemStatus, setRays, updateNode } = useAppStore();

    useEffect(() => {
        if (!enabled) return;
        console.log('[MockData] Indoor Simulation Enabled');

        const W = ROOM_CONFIG.WIDTH / 2;
        // 1. Define Static Sensor Nodes (Opposite ends)
        // Room width is 20m, from -10 to +10.
        // Left Sensor at -10, facing East (90 deg).
        // Right Sensor at 10, facing West (270 deg).
        const SENSORS = [
            { id: "CAM-LEFT", pos: [-W, 0] as [number, number], facing: 90, fov: 90 },
            { id: "CAM-RIGHT", pos: [W, 0] as [number, number], facing: 270, fov: 90 }
        ];

        // 2. Register Sensors
        SENSORS.forEach(sensor => {
            updateNode({
                node_id: sensor.id,
                status: NodeHealthStatus.HEALTHY,
                last_seen: Date.now() / 1000,
                fps: 30,
                cpu_usage: 45,
                temp_c: 52,
                ip_address: "192.168.1.x",
                location: sensor.pos,
                mode: 0,
                config: {
                    azimuth_deg: sensor.facing,
                    fov_deg: sensor.fov,
                    range_meters: 18 // Cover most of the room
                }
            });
        });

        const trackCount = 6;
        const tracks: Record<string, Track> = {};

        // Target destinations for random walking
        const targets: Record<string, [number, number]> = {};

        // Initialize Tracks (People)
        const D = ROOM_CONFIG.DEPTH / 2;

        for (let i = 0; i < trackCount; i++) {
            tracks[i.toString()] = {
                track_id: i,
                state: TrackState.CONFIRMED,
                position: [(Math.random() * ROOM_CONFIG.WIDTH) - W, (Math.random() * ROOM_CONFIG.DEPTH) - D],
                velocity: [0, 0],
                covariance: [],
                first_seen: Date.now() / 1000,
                last_seen: Date.now() / 1000,
                hit_count: 50,
                confidence: 0.95,
                predicted_next: [0, 0],
                history: []
            };
            targets[i.toString()] = [
                (Math.random() * ROOM_CONFIG.WIDTH) - W,
                (Math.random() * ROOM_CONFIG.DEPTH) - D
            ];
        }

        const interval = setInterval(() => {
            const now = Date.now() / 1000;
            const newTracks: Track[] = [];

            // Update Tracks (People movement)
            for (let i = 0; i < trackCount; i++) {
                const t = tracks[i.toString()];
                const target = targets[i.toString()];

                // Vector to target
                const dx = target[0] - t.position[0];
                const dy = target[1] - t.position[1];
                const dist = Math.sqrt(dx * dx + dy * dy);

                // Walking speed ~1.2 m/s
                const speed = 1.2;
                const dt = 0.033; // 33ms

                if (dist < 0.2) {
                    // Pick new target within room bounds
                    targets[i.toString()] = [
                        (Math.random() * ROOM_CONFIG.WIDTH) - W,
                        (Math.random() * ROOM_CONFIG.DEPTH) - D
                    ];
                } else {
                    // Move towards target
                    const vx = (dx / dist) * speed;
                    const vy = (dy / dist) * speed;

                    t.position[0] += vx * dt;
                    t.position[1] += vy * dt;
                    t.velocity = [vx, vy];
                }

                t.last_seen = now;
                newTracks.push({ ...t });
            }

            setTracks(newTracks);

            // Generate Rays (Line of sight)
            const rays: Ray[] = [];
            SENSORS.forEach(sensor => {
                // Determine sensor math angle (Radians, 0 = East, Positive Counter-Clockwise)
                // Nav Angle: 0 = North, 90 = East, 180 = South, 270 = West
                // Math = 90 - Nav
                const sensorMathDeg = 90 - sensor.facing;
                const sensorMathRad = sensorMathDeg * (Math.PI / 180);
                const halfFovRad = (sensor.fov / 2) * (Math.PI / 180);

                newTracks.forEach(track => {
                    const dx = track.position[0] - sensor.pos[0];
                    const dy = track.position[1] - sensor.pos[1];
                    const dist = Math.sqrt(dx * dx + dy * dy);

                    if (dist === 0) return;

                    // Angle to target
                    const targetAngleRad = Math.atan2(dy, dx);

                    // Angle Difference
                    let diff = targetAngleRad - sensorMathRad;
                    // Normalize to [-PI, PI]
                    while (diff > Math.PI) diff -= 2 * Math.PI;
                    while (diff < -Math.PI) diff += 2 * Math.PI;

                    // Check if within FOV
                    if (Math.abs(diff) <= halfFovRad) {
                        rays.push({
                            origin: sensor.pos,
                            direction: [dx / dist, dy / dist],
                            intensity: 150 + Math.random() * 50,
                            camera_id: sensor.id,
                            timestamp: now
                        });
                    }
                });
            });
            setRays(rays);

            updateSystemStatus({
                server_fps: 30,
                total_tracks: trackCount,
                total_voxels: 0,
                uptime_seconds: performance.now() / 1000,
                cpu_percent: 35,
                memory_percent: 42
            });

        }, 33);

        return () => clearInterval(interval);
    }, [enabled, setTracks, updateSystemStatus, setRays, updateNode]);
}
