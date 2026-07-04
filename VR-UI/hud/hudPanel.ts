/**
 * In-scene HUD: a canvas-textured panel that lazily follows the user's gaze
 * (scene-level lerp — never hard head-locked, which is nauseating in VR).
 * Shows connection/geo status, scene counts, the selected track's details
 * and a controller cheat-sheet. Redrawn at ≤4 Hz; the texture upload is the
 * expensive part on a mobile GPU, so don't raise the rate casually.
 */

import * as THREE from 'three';
import { VR_CONFIG } from '../constants';
import { wgs84ToEnu } from '../geo';
import { VRStore } from '../store';
import { assessIntercept, observerVelocityEnu } from '../threat';
import { TrackState } from '../types';

const REDRAW_MS = 250;
const PANEL_W = 0.72;               // metres
const PANEL_H = 0.45;
const FOLLOW_DISTANCE = 1.5;
const FOLLOW_LERP = 0.08;

const ACCENT = VR_CONFIG.COLORS.HUD_ACCENT;
const STATE_NAMES: Record<number, string> = {
    [TrackState.TENTATIVE]: 'TENTATIVE',
    [TrackState.CONFIRMED]: 'CONFIRMED',
    [TrackState.LOST]: 'LOST',
    [TrackState.DELETED]: 'DELETED',
};

export class HudPanel {
    private canvas: HTMLCanvasElement;
    private ctx: CanvasRenderingContext2D;
    private texture: THREE.CanvasTexture;
    private mesh: THREE.Mesh;
    private lastDraw = 0;
    private tmpPos = new THREE.Vector3();
    private tmpDir = new THREE.Vector3();
    private tmpTarget = new THREE.Vector3();

    constructor(scene: THREE.Scene, private store: VRStore) {
        this.canvas = document.createElement('canvas');
        this.canvas.width = 1024;
        this.canvas.height = 640;
        this.ctx = this.canvas.getContext('2d')!;
        this.texture = new THREE.CanvasTexture(this.canvas);
        this.mesh = new THREE.Mesh(
            new THREE.PlaneGeometry(PANEL_W, PANEL_H),
            new THREE.MeshBasicMaterial({
                map: this.texture, transparent: true, depthTest: false,
            }));
        this.mesh.renderOrder = 999;
        this.mesh.position.set(0, 1.3, -FOLLOW_DISTANCE);
        scene.add(this.mesh);
    }

    update(camera: THREE.Camera, nowMs: number, presenting: boolean): void {
        const state = this.store.getState();
        this.mesh.visible = state.hudVisible;
        if (!this.mesh.visible) return;

        // Lazy follow: drift toward a point in front of the user, slightly low.
        camera.getWorldPosition(this.tmpPos);
        camera.getWorldDirection(this.tmpDir);
        this.tmpDir.y *= 0.3;                     // damp vertical head motion
        this.tmpDir.normalize();
        this.tmpTarget.copy(this.tmpPos).addScaledVector(this.tmpDir, FOLLOW_DISTANCE);
        this.tmpTarget.y -= presenting ? 0.25 : 0.1;
        this.mesh.position.lerp(this.tmpTarget, FOLLOW_LERP);
        this.mesh.lookAt(this.tmpPos);

        if (nowMs - this.lastDraw >= REDRAW_MS) {
            this.lastDraw = nowMs;
            this.draw();
        }
    }

    private draw(): void {
        const s = this.store.getState();
        const ctx = this.ctx;
        const W = this.canvas.width;
        const H = this.canvas.height;

        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = 'rgba(2, 8, 4, 0.82)';
        ctx.fillRect(0, 0, W, H);
        ctx.strokeStyle = ACCENT;
        ctx.lineWidth = 3;
        ctx.strokeRect(2, 2, W - 4, H - 4);

        const line = (text: string, x: number, y: number, color = ACCENT, size = 26) => {
            ctx.font = `${size}px monospace`;
            ctx.fillStyle = color;
            ctx.textAlign = 'left';
            ctx.textBaseline = 'top';
            ctx.fillText(text, x, y);
        };

        // Header
        line('OPTICAL RADAR — VR CIC', 24, 18, ACCENT, 34);

        // Connection / mode row
        const nowS = Date.now() / 1000;
        const srv = s.mockMode ? '● SIM' : (s.serverConnected ? '● SERVER'
            : (s.serverReconnectAttempt > 0 ? `○ SERVER (retry ${s.serverReconnectAttempt})` : '○ SERVER'));
        const geoAge = s.geoPose ? nowS - s.geoPose.timestamp : Infinity;
        const geoOk = s.geoConnected && geoAge < VR_CONFIG.GEO_STALE_SECONDS;
        const geoManual = s.geoPose?.provider === 'manual';
        const geo = geoManual ? '● GEO (manual)' : (geoOk ? '● GEO' : (s.geoPose ? '◐ GEO STALE' : '○ GEO'));
        line(srv, 24, 66, (s.mockMode || s.serverConnected) ? ACCENT : '#ff5050');
        line(geo, 300, 66, (geoOk || geoManual) ? ACCENT : '#ffaa00');
        const scaleTxt = s.viewMode === 'TABLETOP'
            ? `TABLETOP 1:${Math.round(1 / s.tabletopScale)}`
            : `AR HUD${s.alignmentHeadingDeg != null ? ` ALIGNED ${s.alignmentHeadingDeg.toFixed(0)}°` : ' — UNALIGNED (press B)'}`;
        line(scaleTxt, 560, 66, s.viewMode === 'HUD' && s.alignmentHeadingDeg == null ? '#ffaa00' : '#ffffff');

        // Counts (+ instant intercept count — same math the overlay smooths)
        let obs: [number, number, number] | null = null;
        let obsVel: [number, number, number] = [0, 0, 0];
        if (s.geoPose) {
            const o = VR_CONFIG.COORDINATE_ORIGIN;
            obs = wgs84ToEnu(s.geoPose.lat, s.geoPose.lon, s.geoPose.alt, o.lat, o.lon, o.alt);
            obsVel = observerVelocityEnu(s.geoPose);
        }
        const threatOf = (t: { position: number[]; velocity: number[] }) => {
            const ob = obs ?? [0, 0, 0];
            return assessIntercept(
                t.position[0] - ob[0], t.position[1] - ob[1], t.position[2] - ob[2],
                t.velocity[0] - obsVel[0], t.velocity[1] - obsVel[1], t.velocity[2] - obsVel[2]);
        };
        const threatCount = Object.values(s.tracks).filter(t => threatOf(t).instant).length;
        const counts = `TRK ${Object.keys(s.tracks).length}   VOX ${s.voxels.length}   ` +
            `RAY ${s.rays.length}   NODES ${Object.keys(s.nodes).length}   ` +
            `SRV ${s.system.server_fps.toFixed(1)} FPS`;
        line(counts, 24, 106, '#c0ffc0');
        if (threatCount > 0) {
            line(`⚠ INTERCEPT ×${threatCount}`, 760, 106, '#ff4040');
        }

        // Geo fix detail
        if (s.geoPose) {
            const p = s.geoPose;
            const hdg = isFinite(p.heading_deg) ? `${p.heading_deg.toFixed(0)}°` : '—';
            line(`FIX ${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}  ±${p.accuracy_m.toFixed(0)}m` +
                `  ALT ${p.alt.toFixed(0)}m  HDG ${hdg}`, 24, 146, '#c0ffc0');
        } else {
            line('FIX — waiting for GeoTether (phone) —', 24, 146, '#808080');
        }

        // Selected track
        ctx.strokeStyle = 'rgba(0,255,65,0.35)';
        ctx.beginPath(); ctx.moveTo(24, 192); ctx.lineTo(W - 24, 192); ctx.stroke();
        if (s.selectedTrackId != null && s.tracks[s.selectedTrackId]) {
            const t = s.tracks[s.selectedTrackId];
            const [vE, vN, vU] = t.velocity;
            const speed = Math.sqrt(vE * vE + vN * vN + vU * vU);
            let heading = Math.atan2(vE, vN) * 180 / Math.PI;
            if (heading < 0) heading += 360;
            // Range + closing rate + intercept verdict relative to the operator.
            let rangeTxt = '';
            let threatTxt = '';
            if (obs) {
                const dE = t.position[0] - obs[0];
                const dN = t.position[1] - obs[1];
                const dU = t.position[2] - obs[2];
                const rng = Math.sqrt(dE * dE + dN * dN + dU * dU);
                if (rng > 1e-3) {
                    const a = threatOf(t);
                    rangeTxt = `RNG ${rng >= 1000 ? (rng / 1000).toFixed(2) + ' km' : rng.toFixed(0) + ' m'}` +
                        `    ${a.closingMs >= 0 ? 'CLOSING' : 'OPENING'} ${Math.abs(a.closingMs).toFixed(1)} m/s`;
                    if (a.instant) {
                        threatTxt = `⚠ INTERCEPT COURSE — TCA ${a.tcaS.toFixed(0)} s   MISS ${a.missM.toFixed(0)} m`;
                    }
                }
            }
            const headerColor = threatTxt ? '#ff4040' : '#ffffff';
            line(`TRACK #${t.track_id}  [${STATE_NAMES[t.state] ?? t.state}]`, 24, 208, headerColor, 30);
            line(`ALT ${t.position[2].toFixed(0)} m    SPD ${speed.toFixed(1)} m/s    HDG ${heading.toFixed(0)}°`, 24, 252);
            line(rangeTxt || `ENU E ${t.position[0].toFixed(0)}  N ${t.position[1].toFixed(0)}  U ${t.position[2].toFixed(0)}`, 24, 290);
            line(threatTxt || `CONF ${(t.confidence * 100).toFixed(0)}%    HITS ${t.hit_count}` +
                (t.physical_size ? `    EST SIZE ${t.physical_size.toFixed(1)} m` : ''), 24, 328,
                threatTxt ? '#ff4040' : ACCENT);
        } else {
            line('NO TRACK SELECTED — point and pull trigger', 24, 208, '#808080');
        }

        // Cheat-sheet
        ctx.strokeStyle = 'rgba(0,255,65,0.35)';
        ctx.beginPath(); ctx.moveTo(24, 384); ctx.lineTo(W - 24, 384); ctx.stroke();
        const help = s.viewMode === 'HUD' ? [
            ['R-TRIGGER select', 'R-A tabletop', 'R-B align north', ''],
            ['L-X compass', 'L-Y node marks', 'L-TRIG labels', ''],
            ['face phone fwd,', 'then press B', 'to align', ''],
        ] : [
            ['R-TRIGGER select', 'R-A hud mode', 'R-B reset', 'R-STICK rot/zoom'],
            ['L-X rays', 'L-Y voxels', 'L-TRIG trails', 'L-STICK pan'],
            ['L-GRIP grab table', 'R-STICK-CLK center', 'L-STICK-CLK panel', ''],
        ];
        help.forEach((row, r) => {
            row.forEach((cell, c) => {
                if (cell) line(cell, 24 + c * 250, 402 + r * 34, '#70c090', 20);
            });
        });

        // Layer states
        const flag = (on: boolean, name: string) => `${on ? '■' : '□'} ${name}`;
        const flags = s.viewMode === 'HUD'
            ? `${flag(s.showCompass, 'COMPASS')}   ${flag(s.showNodeMarkers, 'NODES')}   ${flag(s.showLabels, 'LABELS')}`
            : `${flag(s.showRays, 'RAYS')}   ${flag(s.showVoxels, 'VOXELS')}   ${flag(s.showTrails, 'TRAILS')}`;
        line(flags, 24, 560, '#c0ffc0', 24);
        if (s.activeClusterId) line(`DOMAIN ${s.activeClusterId}`, 560, 560, '#c0ffc0', 24);

        this.texture.needsUpdate = true;
    }
}
