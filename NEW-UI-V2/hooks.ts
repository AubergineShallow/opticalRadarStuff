
import { useEffect, useRef, useState, useCallback } from 'react';
import { useAppStore } from './store';
import { Track, TrackState, NodeHealthStatus, NodeHealth, Ray, WSMessage } from './types';
import { UI_CONFIG } from './constants';

// ENU -> LLA reference (single source of truth; was copy-pasted into TargetList
// and SensorList — P3.2). cos(refLat) is precomputed once at module load.
const REF_LAT = UI_CONFIG.INITIAL_VIEW_STATE.latitude;
const REF_LON = UI_CONFIG.INITIAL_VIEW_STATE.longitude;
const COS_REF_LAT = Math.cos(REF_LAT * Math.PI / 180);

/** Precompute speed/heading/lat/lon once, at WebSocket receipt (P3.2). */
function enrichTrack(track: Track): Track {
    const [vE, vN, vU] = track.velocity;
    const [pE, pN] = track.position;
    let heading = Math.atan2(vE, vN) * (180 / Math.PI);
    if (heading < 0) heading += 360;
    return {
        ...track,
        display: {
            speed_ms: Math.sqrt(vE * vE + vN * vN + vU * vU),
            heading_deg: heading,
            lat: REF_LAT + pN / 111111,
            lon: REF_LON + pE / (111111 * COS_REF_LAT),
        }
    };
}

/** Precompute display lat/lon for a node; tolerate backend `id` vs `node_id`. */
function enrichNode(node: NodeHealth): NodeHealth {
    const [pE, pN] = node.location || [0, 0, 0];
    return {
        ...node,
        node_id: node.node_id || (node as any).id,
        display_lat: REF_LAT + pN / 111111,
        display_lon: REF_LON + pE / (111111 * COS_REF_LAT),
    };
}

/**
 * Hook to manage WebSocket connection to the Python backend.
 * Parses incoming JSON messages and dispatches updates to the Zustand store.
 * Returns { isConnected, sendCommand } — sendCommand buffers messages while the
 * socket is still connecting so a click during reconnect is not dropped (P3.5).
 */
export function useWebSocket(url: string, enabled: boolean = true) {
    const {
        setTracks,
        setVoxels,
        setRays,
        updateNode,
        updateSystemStatus,
        setClusters,
        setPendingNodes,
    } = useAppStore();

    const activeClusterId = useAppStore(s => s.activeClusterId);

    const [isConnected, setIsConnected] = useState(false);
    const wsRef = useRef<WebSocket | null>(null);
    const sendQueueRef = useRef<string[]>([]);

    const sendCommand = useCallback((type: string, payload: any = {}) => {
        const msg = JSON.stringify({ type, payload });
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(msg);
        } else {
            // Buffer until the socket opens (e.g. a click during reconnect).
            sendQueueRef.current.push(msg);
        }
    }, []);

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
            // Flush any commands buffered while connecting.
            const queued = sendQueueRef.current;
            sendQueueRef.current = [];
            queued.forEach(m => ws.send(m));
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
                        setTracks((message.payload as Track[]).map(enrichTrack));
                        break;
                    case 'VOXEL_UPDATE':
                        setVoxels(message.payload);
                        break;
                    case 'RAY_UPDATE':
                        setRays(message.payload);
                        break;
                    case 'NODE_UPDATE':
                        // Payload may be an array of NodeHealth or a single update.
                        if (Array.isArray(message.payload)) {
                            message.payload.forEach((node: NodeHealth) => updateNode(enrichNode(node)));
                        } else {
                            updateNode(enrichNode(message.payload));
                        }
                        break;
                    case 'SYSTEM_STATUS':
                        updateSystemStatus(message.payload);
                        break;
                    case 'CLUSTER_UPDATE': {
                        const payload = message.payload || {};
                        if (payload.clusters) setClusters(payload.clusters);
                        if (payload.pending_nodes) setPendingNodes(payload.pending_nodes);
                        break;
                    }
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
    }, [url, enabled, setTracks, setVoxels, setRays, updateNode, updateSystemStatus,
        setClusters, setPendingNodes]);

    // Subscribe to the active cluster's room whenever it changes (P3.5).
    useEffect(() => {
        if (enabled && isConnected && activeClusterId) {
            sendCommand('SUBSCRIBE_CLUSTER', { cluster_id: activeClusterId });
        }
    }, [enabled, isConnected, activeClusterId, sendCommand]);

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

        // 2. Register Sensors on Map (enriched with precomputed display lat/lon)
        SENSORS.forEach(sensor => {
            updateNode(enrichNode({
                node_id: sensor.id,
                status: NodeHealthStatus.HEALTHY,
                last_seen: Date.now() / 1000,
                fps: 60,
                cpu_usage: 30 + Math.random() * 10,
                temp_c: 45,
                ip_address: "10.0.0.x",
                location: sensor.pos
            }));
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

            setTracks(newTracks.map(enrichTrack));

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
