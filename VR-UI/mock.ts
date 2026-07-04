/**
 * Mock data generator (?mock=true) — frontend-only simulated scene, ported
 * from NEW-UI-V2's useMockData: three sensors, five orbiting tracks, per-
 * sensor bearing rays and ~1 Hz node heartbeats (without which the nodes
 * would correctly go STALE). Additions over the 2D mock: voxel cloud around
 * each track (the 2D mock never mocked voxels) and a mock GEO_POSE so WORLD
 * mode + alignment can be exercised without a phone.
 */

import { VRStore } from './store';
import { VR_CONFIG } from './constants';
import { wgs84ToEnu } from './geo';
import {
    Track, TrackState, Ray, Voxel, NodeHealthStatus,
} from './types';

// The mock operator wanders ±0.0001° (~11 m) around the origin; ONE source
// of truth for it, because the interceptor must aim at the observer's real
// position or it never enters the near-field depth regime.
function mockObserverWgs84(now: number): { lat: number; lon: number; alt: number } {
    const o = VR_CONFIG.COORDINATE_ORIGIN;
    return {
        lat: o.lat + 0.0001 * Math.sin(now / 30),
        lon: o.lon + 0.0001 * Math.cos(now / 30),
        alt: o.alt + 2,
    };
}

function mockObserverEnu(now: number): [number, number, number] {
    const o = VR_CONFIG.COORDINATE_ORIGIN;
    const p = mockObserverWgs84(now);
    return wgs84ToEnu(p.lat, p.lon, p.alt, o.lat, o.lon, o.alt);
}

export function startMockData(store: VRStore): () => void {
    console.log('[MockData] Enabled');
    const s = store.getState();

    const SENSORS = [
        { id: 'NODE-ALPHA', pos: [-800, -800, 30] as [number, number, number] },   // SW
        { id: 'NODE-BRAVO', pos: [800, -800, 45] as [number, number, number] },    // SE
        { id: 'NODE-CHARLIE', pos: [0, 1000, 60] as [number, number, number] },    // N
    ];

    const heartbeat = (now: number) => {
        SENSORS.forEach(sensor => {
            s.updateNode({
                node_id: sensor.id,
                status: NodeHealthStatus.HEALTHY,
                last_seen: now,
                fps: 58 + Math.random() * 4,
                cpu_usage: 30 + Math.random() * 10,
                temp_c: 44 + Math.random() * 3,
                ip_address: '10.0.0.x',
                location: sensor.pos,
            });
        });
    };
    heartbeat(Date.now() / 1000);

    const trackCount = 5;
    let tick = 0;

    // Interceptor: a track that flies straight at the (mock) observer near
    // the ENU origin — exercises the headset-side CBDR warning and the
    // close-range depth cues. Respawns on a fresh bearing after each pass.
    const INTERCEPTOR_ID = trackCount;
    let intPos: [number, number, number] = [0, 0, 0];
    const spawnInterceptor = () => {
        const bearing = Math.random() * Math.PI * 2;
        intPos = [Math.sin(bearing) * 1500, Math.cos(bearing) * 1500, 200];
    };
    spawnInterceptor();

    const interval = setInterval(() => {
        const now = Date.now() / 1000;

        if (tick % 30 === 0) heartbeat(now);
        tick++;

        // Orbiting targets (same parametric paths as the 2D mock)
        const newTracks: Track[] = [];
        for (let i = 0; i < trackCount; i++) {
            const r = 300 + i * 80;
            const speed = 0.4 + i * 0.15;
            const angle = now * speed;
            const alt = 150 + Math.sin(angle * 3) * 40;
            newTracks.push({
                track_id: i,
                state: i === trackCount - 1 ? TrackState.TENTATIVE : TrackState.CONFIRMED,
                position: [Math.cos(angle) * r, Math.sin(angle) * r, alt],
                velocity: [
                    -Math.sin(angle) * speed * r,
                    Math.cos(angle) * speed * r,
                    Math.cos(angle * 3) * 120 * speed,
                ],
                covariance: [],
                first_seen: now,
                last_seen: now,
                hit_count: 10,
                confidence: 0.9,
                predicted_next: [0, 0, 100],
                physical_size: 1.5 + i * 2.5,
            });
        }
        // Advance the interceptor toward the observer's ACTUAL position.
        // It decelerates close-in (45 → 6 m/s) so it spends a couple of
        // seconds inside the annotation dome, exercising the near-field
        // true-depth placement, then respawns on a new bearing.
        {
            const [obsE, obsN, obsU] = mockObserverEnu(now);
            const dx = obsE - intPos[0], dy = obsN - intPos[1], dz = obsU - intPos[2];
            const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
            if (dist < 8) spawnInterceptor();
            const speed = Math.min(45, Math.max(6, dist * 0.15));
            const d2 = Math.max(1, dist);
            const vel: [number, number, number] = [
                dx / d2 * speed, dy / d2 * speed, dz / d2 * speed];
            intPos = [intPos[0] + vel[0] * 0.033, intPos[1] + vel[1] * 0.033, intPos[2] + vel[2] * 0.033];
            newTracks.push({
                track_id: INTERCEPTOR_ID,
                state: TrackState.CONFIRMED,
                position: [...intPos] as [number, number, number],
                velocity: vel,
                covariance: [],
                first_seen: now,
                last_seen: now,
                hit_count: 12,
                confidence: 0.95,
                predicted_next: [...intPos] as [number, number, number],
                physical_size: 0.8,
            });
        }

        s.setTracks(newTracks);

        // Bearing rays from each sensor to each target
        const rays: Ray[] = [];
        SENSORS.forEach(sensor => {
            newTracks.forEach(track => {
                const dx = track.position[0] - sensor.pos[0];
                const dy = track.position[1] - sensor.pos[1];
                const dz = track.position[2] - sensor.pos[2];
                const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
                const noise = () => (Math.random() - 0.5) * 0.01;
                rays.push({
                    origin: sensor.pos,
                    direction: [dx / dist + noise(), dy / dist + noise(), dz / dist + noise()],
                    intensity: 200,
                    camera_id: sensor.id,
                    timestamp: now,
                });
            });
        });
        s.setRays(rays);

        // Voxel heat around each target (quantized to the grid pitch)
        const voxels: Voxel[] = [];
        const pitch = VR_CONFIG.VOXEL_SIZE_METERS;
        newTracks.forEach(track => {
            for (let ox = -1; ox <= 1; ox++) {
                for (let oy = -1; oy <= 1; oy++) {
                    for (let oz = 0; oz <= 1; oz++) {
                        const heat = 255 - (Math.abs(ox) + Math.abs(oy) + Math.abs(oz)) * 70;
                        if (heat < 80) continue;
                        voxels.push({
                            x: Math.round(track.position[0] / pitch) * pitch + ox * pitch,
                            y: Math.round(track.position[1] / pitch) * pitch + oy * pitch,
                            z: Math.round(track.position[2] / pitch) * pitch + oz * pitch,
                            intensity: heat,
                            timestamp: now,
                        });
                    }
                }
            }
        });
        s.setVoxels(voxels);

        s.updateSystemStatus({
            server_fps: 29.5 + Math.random(),
            total_tracks: trackCount,
            total_voxels: voxels.length,
            uptime_seconds: performance.now() / 1000,
            cpu_percent: 20 + Math.random() * 5,
            memory_percent: 45 + Math.random() * 2,
        });
    }, 33); // ~30 Hz, matching the real broadcast rate

    // Mock operator fix: near the origin, drifting compass — lets HUD mode
    // and the align action be exercised without a phone.
    const geoInterval = setInterval(() => {
        const now = Date.now() / 1000;
        const p = mockObserverWgs84(now);
        s.setGeoPose({
            lat: p.lat,
            lon: p.lon,
            alt: p.alt,
            accuracy_m: 3 + Math.random() * 2,
            heading_deg: (now * 2) % 360,
            heading_accuracy_deg: 10,
            speed_ms: 0,
            timestamp: now,
            provider: 'mock',
        });
        s.setGeoConnected(true);
    }, 500);

    return () => {
        clearInterval(interval);
        clearInterval(geoInterval);
    };
}
