import { useEffect } from 'react';
import { useAppStore } from './store';
import { Track, TrackState, NodeHealthStatus, Ray, WSMessage } from './types';
import { useRef, useState } from 'react';

/**
 * Hook to manage WebSocket connection to the Python backend.
 * Parses incoming JSON messages and dispatches updates to the Zustand store.
 */
export function useWebSocket(url: string, enabled: boolean = true) {
    const {
        setTracks,
        setVoxels,
        setRays,
        updateNode,
        updateSystemStatus,
        setClusters,
        setPendingNodes
    } = useAppStore();

    const [isConnected, setIsConnected] = useState(false);
    const sendCommand = (cmd: string, data?: any) => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: cmd, payload: data || {} }));
        } else {
            console.warn('[WebSocket] Cannot send command, socket not open:', cmd);
        }
    };
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
                        // Payload is an array of NodeHealth, store expects individual updates
                        if (Array.isArray(message.payload)) {
                            message.payload.forEach((node: any) => updateNode(node));
                        } else {
                            updateNode(message.payload);
                        }
                        break;
                    case 'SYSTEM_STATUS':
                        updateSystemStatus(message.payload);
                        if (message.payload.clusters) {
                            setClusters(message.payload.clusters);
                        }
                        if (message.payload.pending_nodes) {
                            setPendingNodes(message.payload.pending_nodes);
                        }
                        break;
                    case 'CLUSTER_UPDATE':
                        if (message.payload.clusters) {
                            setClusters(message.payload.clusters);
                        }
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

    return { isConnected, sendCommand };
}

export function useMockData(enabled: boolean = true) {
    const { setTracks, updateSystemStatus, setRays, setVoxels, updateNode } = useAppStore();

    useEffect(() => {
        if (!enabled) return;
        console.log('[MockData] Hook Enabled');

        // 1. Define Static Sensor Nodes (Distributed Network)
        const SENSORS = [
            { id: "NODE-ALPHA", pos: [-800, -800, 30] as [number, number, number] }, // SW
            { id: "NODE-BRAVO", pos: [800, -800, 45] as [number, number, number] },  // SE
            { id: "NODE-CHARLIE", pos: [0, 1000, 60] as [number, number, number] }   // N
        ];

        // 2. Register Sensors on Map
        SENSORS.forEach(sensor => {
            updateNode({
                node_id: sensor.id,
                status: NodeHealthStatus.HEALTHY,
                last_seen: Date.now() / 1000,
                fps: 60,
                cpu_usage: 30 + Math.random() * 10,
                temp_c: 45,
                ip_address: "10.0.0.x",
                location: sensor.pos
            });
        });

        // Simulate tracks
        const tracks: Record<string, Track> = {};
        const trackCount = 5;

        // Initialize Tracks
        for (let i = 0; i < trackCount; i++) {
            tracks[i.toString()] = {
                track_id: i,
                state: TrackState.CONFIRMED,
                position: [0, 0, 100],
                velocity: [10, 0, 0],
                covariance: [],
                first_seen: Date.now() / 1000,
                last_seen: Date.now() / 1000,
                hit_count: 10,
                confidence: 0.9,
                predicted_next: [0, 0, 100]
            };
        }

        const interval = setInterval(() => {
            const now = Date.now() / 1000;
            const newTracks: Track[] = [];

            // Update Tracks (Target Simulation)
            for (let i = 0; i < trackCount; i++) {
                const t = tracks[i.toString()];

                // Circular motion path with varying parameters
                const r = 300 + i * 80;
                const speed = 0.4 + i * 0.15;
                const angle = now * speed;

                // Add some vertical sine wave motion
                const alt = 150 + Math.sin(angle * 3) * 40;

                t.position = [
                    Math.cos(angle) * r,
                    Math.sin(angle) * r,
                    alt
                ];

                t.last_seen = now;
                // Derive velocity from position derivative (approx)
                t.velocity = [
                    -Math.sin(angle) * speed * r,
                    Math.cos(angle) * speed * r,
                    Math.cos(angle * 3) * 120 * speed // z-velocity
                ];

                newTracks.push({ ...t });
            }

            setTracks(newTracks);

            // Generate Rays (Sensor Simulation)
            // Each sensor "sees" the targets and reports a bearing (Az/El ray)
            const rays: Ray[] = [];

            SENSORS.forEach(sensor => {
                newTracks.forEach(track => {
                    // Calculate vector from sensor to target
                    const dx = track.position[0] - sensor.pos[0];
                    const dy = track.position[1] - sensor.pos[1];
                    const dz = track.position[2] - sensor.pos[2];

                    // Normalize to get direction
                    const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);

                    // Add slight sensor noise to the bearing
                    const noise = () => (Math.random() - 0.5) * 0.01;

                    rays.push({
                        origin: sensor.pos,
                        direction: [
                            (dx / distance) + noise(),
                            (dy / distance) + noise(),
                            (dz / distance) + noise()
                        ],
                        intensity: 200,
                        camera_id: sensor.id,
                        timestamp: now
                    });
                });
            });
            setRays(rays);

            // Mock System Status
            updateSystemStatus({
                server_fps: 29.5 + Math.random(),
                total_tracks: trackCount,
                total_voxels: SENSORS.length, // repurposed for active sensors count in this mock
                uptime_seconds: performance.now() / 1000,
                cpu_percent: 20 + Math.random() * 5,
                memory_percent: 45 + Math.random() * 2
            });

        }, 33); // ~30fps

        return () => clearInterval(interval);
    }, [enabled, setTracks, updateSystemStatus, setRays, setVoxels, updateNode]);
}