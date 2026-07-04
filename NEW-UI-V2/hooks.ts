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
// Exponential-backoff bounds for reconnection (ms).
const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 10000;

export function useWebSocket(url: string, enabled: boolean = true) {
    const activeClusterId = useAppStore(s => s.activeClusterId);

    const [isConnected, setIsConnected] = useState(false);
    // Mirrors attemptsRef into state so the UI can show reconnect progress
    // ("RECONNECTING (3)") instead of a bare DISCONNECTED while backing off.
    const [reconnectAttempt, setReconnectAttempt] = useState(0);
    const wsRef = useRef<WebSocket | null>(null);
    const sendQueueRef = useRef<string[]>([]);
    const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const attemptsRef = useRef(0);
    // Set during teardown so an intentional close does not trigger a reconnect.
    const closedByUsRef = useRef(false);

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

        closedByUsRef.current = false;
        let cancelled = false;

        const dispatchMessage = (event: MessageEvent) => {
            try {
                const message: WSMessage = JSON.parse(event.data);
                // Setters are pulled fresh from the store (stable refs) so the
                // connection effect does not need them as dependencies and can
                // own the socket lifecycle across reconnects.
                const store = useAppStore.getState();

                switch (message.type) {
                    case 'TRACK_UPDATE':
                        store.setTracks((message.payload as Track[]).map(enrichTrack));
                        break;
                    case 'VOXEL_UPDATE':
                        store.setVoxels(message.payload);
                        break;
                    case 'RAY_UPDATE':
                        store.setRays(message.payload);
                        break;
                    case 'NODE_UPDATE':
                        // Payload may be an array of NodeHealth or a single update.
                        if (Array.isArray(message.payload)) {
                            message.payload.forEach((node: NodeHealth) => store.updateNode(enrichNode(node)));
                        } else {
                            store.updateNode(enrichNode(message.payload));
                        }
                        break;
                    case 'SYSTEM_STATUS':
                        store.updateSystemStatus(message.payload);
                        // Per-node calibration status rides along in the status
                        // payload (P1.5); surface it for the sensor list.
                        if (message.payload && message.payload.calibration) {
                            store.setCalibration(message.payload.calibration);
                        }
                        break;
                    case 'CLUSTER_UPDATE': {
                        const payload = message.payload || {};
                        if (payload.clusters) store.setClusters(payload.clusters);
                        if (payload.pending_nodes) store.setPendingNodes(payload.pending_nodes);
                        break;
                    }
                    default:
                        console.warn('[WebSocket] Unknown message type:', (message as any).type);
                }
            } catch (err) {
                console.error('[WebSocket] Failed to parse message:', err);
            }
        };

        const scheduleReconnect = () => {
            if (cancelled || closedByUsRef.current) return;
            // Exponential backoff, capped, so a backend that is down does not get
            // hammered but the UI still recovers automatically when it returns.
            const delay = Math.min(
                RECONNECT_MAX_MS,
                RECONNECT_BASE_MS * 2 ** attemptsRef.current
            );
            attemptsRef.current += 1;
            setReconnectAttempt(attemptsRef.current);
            console.log(`[WebSocket] Reconnecting in ${delay} ms...`);
            reconnectTimerRef.current = setTimeout(connect, delay);
        };

        const connect = () => {
            if (cancelled) return;
            console.log(`[WebSocket] Connecting to ${url}...`);
            const ws = new WebSocket(url);
            wsRef.current = ws;

            ws.onopen = () => {
                console.log('[WebSocket] Connected');
                attemptsRef.current = 0;
                setReconnectAttempt(0);
                setIsConnected(true);
                // Re-subscribe to the active room after a reconnect, then flush
                // any commands buffered while the socket was down.
                const active = useAppStore.getState().activeClusterId;
                if (active) {
                    ws.send(JSON.stringify({ type: 'SUBSCRIBE_CLUSTER', payload: { cluster_id: active } }));
                }
                const queued = sendQueueRef.current;
                sendQueueRef.current = [];
                queued.forEach(m => ws.send(m));
            };

            ws.onclose = () => {
                setIsConnected(false);
                if (!closedByUsRef.current) {
                    console.log('[WebSocket] Disconnected; will retry');
                    scheduleReconnect();
                }
            };

            ws.onerror = () => {
                // onclose fires after onerror and owns the reconnect; just close.
                ws.close();
            };

            ws.onmessage = dispatchMessage;
        };

        connect();

        return () => {
            cancelled = true;
            closedByUsRef.current = true;
            if (reconnectTimerRef.current) {
                clearTimeout(reconnectTimerRef.current);
                reconnectTimerRef.current = null;
            }
            const ws = wsRef.current;
            if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
                ws.close();
            }
        };
    }, [url, enabled]);

    // Subscribe to the active cluster's room whenever it changes (P3.5).
    useEffect(() => {
        if (enabled && isConnected && activeClusterId) {
            sendCommand('SUBSCRIBE_CLUSTER', { cluster_id: activeClusterId });
        }
    }, [enabled, isConnected, activeClusterId, sendCommand]);

    return { isConnected, sendCommand, reconnectAttempt };
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
                predicted_next: [0, 0, 100],
                // Mirrors the server's fused-angular-size estimate so sim mode
                // exercises the Est. Size display (drone-to-aircraft scale).
                physical_size: 1.5 + i * 2.5
            };
        }

        let tick = 0;
        const interval = setInterval(() => {
            const now = Date.now() / 1000;
            const newTracks: Track[] = [];

            // Refresh sensor heartbeats ~1 Hz. Without this the nodes were
            // registered once with a fixed last_seen and the sensor list
            // (correctly) flagged them all STALE after 10 s of sim time.
            if (tick % 30 === 0) {
                SENSORS.forEach(sensor => {
                    updateNode(enrichNode({
                        node_id: sensor.id,
                        status: NodeHealthStatus.HEALTHY,
                        last_seen: now,
                        fps: 58 + Math.random() * 4,
                        cpu_usage: 30 + Math.random() * 10,
                        temp_c: 44 + Math.random() * 3,
                        ip_address: "10.0.0.x",
                        location: sensor.pos
                    }));
                });
            }
            tick++;

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
