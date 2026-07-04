/**
 * Reconnecting WebSocket client for the OpticalRadar server broadcast
 * (ws://<server>:5000/ws). Framework-free port of NEW-UI-V2's useWebSocket —
 * all of its hard-won behaviour is preserved:
 *  - exponential backoff 500 ms → 10 s, automatic recovery,
 *  - intentional close() never triggers a reconnect,
 *  - commands sent while disconnected are QUEUED and flushed on open,
 *  - SUBSCRIBE_CLUSTER is re-sent after every reconnect and whenever the
 *    active cluster changes.
 */

import { VRStore } from '../store';
import { Track, NodeHealth, WSMessage } from '../types';

const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 10000;

export class ServerSocket {
    private ws: WebSocket | null = null;
    private sendQueue: string[] = [];
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private attempts = 0;
    private closedByUs = false;
    private unsubStore: (() => void) | null = null;
    private lastSubscribedCluster: string | null = null;

    constructor(private url: string, private store: VRStore) {}

    connect(): void {
        this.closedByUs = false;
        // Re-subscribe when the active cluster changes (parity with the
        // NEW-UI-V2 hook's second effect).
        this.unsubStore = this.store.subscribe((s, prev) => {
            if (s.activeClusterId !== prev.activeClusterId && s.activeClusterId
                && s.activeClusterId !== this.lastSubscribedCluster) {
                this.subscribeCluster(s.activeClusterId);
            }
        });
        this.open();
    }

    close(): void {
        this.closedByUs = true;
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.unsubStore) {
            this.unsubStore();
            this.unsubStore = null;
        }
        const ws = this.ws;
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
            ws.close();
        }
    }

    /** Send a command, buffering it if the socket is down (never dropped). */
    sendCommand(type: string, payload: any = {}): void {
        const msg = JSON.stringify({ type, payload });
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(msg);
        } else {
            this.sendQueue.push(msg);
        }
    }

    private subscribeCluster(clusterId: string): void {
        this.lastSubscribedCluster = clusterId;
        this.sendCommand('SUBSCRIBE_CLUSTER', { cluster_id: clusterId });
    }

    private open(): void {
        console.log(`[ServerSocket] Connecting to ${this.url}...`);
        const ws = new WebSocket(this.url);
        this.ws = ws;

        ws.onopen = () => {
            console.log('[ServerSocket] Connected');
            this.attempts = 0;
            this.store.getState().setServerConnected(true, 0);
            // Re-subscribe to the active room, then flush buffered commands.
            const active = this.store.getState().activeClusterId;
            if (active) {
                this.lastSubscribedCluster = active;
                ws.send(JSON.stringify({ type: 'SUBSCRIBE_CLUSTER', payload: { cluster_id: active } }));
            }
            const queued = this.sendQueue;
            this.sendQueue = [];
            queued.forEach(m => ws.send(m));
        };

        ws.onclose = () => {
            this.store.getState().setServerConnected(false, this.attempts);
            if (!this.closedByUs) {
                console.log('[ServerSocket] Disconnected; will retry');
                this.scheduleReconnect();
            }
        };

        ws.onerror = () => {
            // onclose fires after onerror and owns the reconnect; just close.
            ws.close();
        };

        ws.onmessage = (event) => this.dispatch(event);
    }

    private scheduleReconnect(): void {
        if (this.closedByUs) return;
        const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** this.attempts);
        this.attempts += 1;
        this.store.getState().setServerConnected(false, this.attempts);
        console.log(`[ServerSocket] Reconnecting in ${delay} ms...`);
        this.reconnectTimer = setTimeout(() => this.open(), delay);
    }

    private dispatch(event: MessageEvent): void {
        try {
            const message: WSMessage = JSON.parse(event.data);
            const store = this.store.getState();

            switch (message.type) {
                case 'TRACK_UPDATE':
                    store.setTracks(message.payload as Track[]);
                    break;
                case 'VOXEL_UPDATE':
                    store.setVoxels(message.payload);
                    break;
                case 'RAY_UPDATE':
                    store.setRays(message.payload);
                    break;
                case 'NODE_UPDATE':
                    // Payload may be an array or a single update; tolerate the
                    // backend's `id` vs `node_id` naming.
                    if (Array.isArray(message.payload)) {
                        message.payload.forEach((n: NodeHealth) => store.updateNode(normalizeNode(n)));
                    } else {
                        store.updateNode(normalizeNode(message.payload));
                    }
                    break;
                case 'SYSTEM_STATUS':
                    store.updateSystemStatus(message.payload);
                    if (message.payload && message.payload.calibration) {
                        store.setCalibration(message.payload.calibration);
                    }
                    break;
                case 'CLUSTER_UPDATE': {
                    const payload = message.payload || {};
                    if (payload.clusters) store.setClusters(payload.clusters);
                    break;
                }
                default:
                    console.warn('[ServerSocket] Unknown message type:', (message as any).type);
            }
        } catch (err) {
            console.error('[ServerSocket] Failed to parse message:', err);
        }
    }
}

function normalizeNode(node: NodeHealth): NodeHealth {
    return { ...node, node_id: node.node_id || (node as any).id };
}
