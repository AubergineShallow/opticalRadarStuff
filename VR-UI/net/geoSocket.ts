/**
 * Reconnecting WebSocket client for the GeoTether companion app on the
 * tethered Android phone (the Steam Frame has no GNSS; the phone streams
 * GEO_POSE over the USB/WiFi tether — see vr_companion_android/).
 *
 * Same reconnect discipline as ServerSocket (backoff 500 ms → 10 s,
 * intentional close never reconnects). No outbound commands — the feed is
 * one-way phone → headset.
 */

import { VRStore } from '../store';
import { GeoPose, GeoWSMessage } from '../types';

const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 10000;

export class GeoSocket {
    private ws: WebSocket | null = null;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private attempts = 0;
    private closedByUs = false;

    constructor(private url: string, private store: VRStore) {}

    connect(): void {
        this.closedByUs = false;
        this.open();
    }

    close(): void {
        this.closedByUs = true;
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        const ws = this.ws;
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
            ws.close();
        }
    }

    private open(): void {
        console.log(`[GeoSocket] Connecting to ${this.url}...`);
        const ws = new WebSocket(this.url);
        this.ws = ws;

        ws.onopen = () => {
            console.log('[GeoSocket] Connected to GeoTether');
            this.attempts = 0;
            this.store.getState().setGeoConnected(true);
        };

        ws.onclose = () => {
            this.store.getState().setGeoConnected(false);
            if (!this.closedByUs) {
                this.scheduleReconnect();
            }
        };

        ws.onerror = () => {
            ws.close();
        };

        ws.onmessage = (event) => {
            try {
                const message: GeoWSMessage = JSON.parse(event.data);
                if (message.type === 'GEO_POSE') {
                    const p = message.payload;
                    // Minimal sanity: reject non-finite / out-of-range fixes so a
                    // buggy sender can't fling the world group to NaN-land.
                    if (!isFinite(p.lat) || !isFinite(p.lon) || Math.abs(p.lat) > 90 || Math.abs(p.lon) > 180) {
                        return;
                    }
                    const pose: GeoPose = {
                        lat: p.lat,
                        lon: p.lon,
                        alt: isFinite(p.alt) ? p.alt : 0,
                        accuracy_m: isFinite(p.accuracy_m) ? p.accuracy_m : 9999,
                        heading_deg: isFinite(p.heading_deg) ? p.heading_deg : NaN,
                        heading_accuracy_deg: isFinite(p.heading_accuracy_deg) ? p.heading_accuracy_deg : NaN,
                        speed_ms: isFinite(p.speed_ms) ? p.speed_ms : 0,
                        timestamp: isFinite(p.timestamp) ? p.timestamp : Date.now() / 1000,
                        provider: typeof p.provider === 'string' ? p.provider : 'fused',
                    };
                    this.store.getState().setGeoPose(pose);
                } else if (message.type === 'HELLO') {
                    console.log('[GeoSocket] GeoTether hello:', JSON.stringify(message.payload));
                }
            } catch (err) {
                console.error('[GeoSocket] Failed to parse message:', err);
            }
        };
    }

    private scheduleReconnect(): void {
        if (this.closedByUs) return;
        const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** this.attempts);
        this.attempts += 1;
        console.log(`[GeoSocket] Reconnecting in ${delay} ms...`);
        this.reconnectTimer = setTimeout(() => this.open(), delay);
    }
}
