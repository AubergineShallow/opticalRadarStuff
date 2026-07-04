/**
 * HUD overlay — the AR/MR "look at the sky" mode.
 *
 * Each track gets a target designator drawn on a head-centered annotation
 * dome (DOME_RADIUS_M) in the track's TRUE direction from the observer:
 *   direction = R_y(alignHeading) · scene(track_ENU − observer_ENU)
 * with the observer position from the phone's GEO_POSE. Designators keep a
 * nominal ANGULAR size and carry range/altitude labels and a velocity
 * leader — rendering a 2 km drone at 1:1 scale would be an invisible dot,
 * so this is the standard far-field AR annotation approach.
 *
 * Depth cues (VR_CONFIG.DEPTH): designator size attenuates with range
 * around REF_RANGE_M, far targets fade, and targets closer than the dome
 * radius are placed at their TRUE distance so real stereopsis and motion
 * parallax take over close-in.
 *
 * Intercept cueing (threat.ts, VR_CONFIG.THREAT): tracks on a collision
 * course (closing + small predicted miss) flash, get a pulsing ring, a
 * "!!" label and top edge-arrow priority. Per-track EMA + hysteresis keep
 * noisy velocity estimates from flickering the warning. All of it computed
 * on the headset.
 *
 * Also owns: horizon ring + compass ticks on the dome (world-aligned, so
 * they behave like a real compass as the head turns), sensor-node ground
 * markers, and camera-locked edge arrows pointing at off-screen tracks.
 */

import * as THREE from 'three';
import { VR_CONFIG } from '../constants';
import { wgs84ToEnu } from '../geo';
import { VRState } from '../store';
import { assessIntercept, observerVelocityEnu } from '../threat';
import { Track, TrackState, NodeHealthStatus } from '../types';
import { makeLabelSprite, setLabelText } from './entities';

const C = VR_CONFIG.COLORS;
const H = VR_CONFIG.HUD;
const T = VR_CONFIG.THREAT;
const D = VR_CONFIG.DEPTH;
const DEG = Math.PI / 180;

const DOME_R = H.DOME_RADIUS_M;
const MARKER_SIZE = 2 * DOME_R * Math.tan(H.MARKER_ANGULAR_DEG * DEG / 2);
const LABEL_W = 2 * DOME_R * Math.tan(H.LABEL_ANGULAR_DEG * DEG / 2);
const THREAT_FLASH_COLOR = 0xffff40;

// ---------------------------------------------------------------------------
// Shared glyph textures: white shapes on transparent, tinted per-sprite via
// SpriteMaterial.color.
// ---------------------------------------------------------------------------

type GlyphKind = 'diamond' | 'square' | 'cross' | 'triangle' | 'arrow' | 'ring';

const glyphCache = new Map<GlyphKind, THREE.CanvasTexture>();

function glyphTexture(kind: GlyphKind): THREE.CanvasTexture {
    let tex = glyphCache.get(kind);
    if (tex) return tex;
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 128;
    const ctx = canvas.getContext('2d')!;
    ctx.strokeStyle = '#ffffff';
    ctx.fillStyle = '#ffffff';
    ctx.lineWidth = 10;
    ctx.lineJoin = 'round';
    switch (kind) {
        case 'diamond':
            ctx.beginPath();
            ctx.moveTo(64, 12); ctx.lineTo(116, 64); ctx.lineTo(64, 116); ctx.lineTo(12, 64);
            ctx.closePath(); ctx.stroke();
            break;
        case 'square':
            ctx.strokeRect(20, 20, 88, 88);
            break;
        case 'cross':
            ctx.beginPath();
            ctx.moveTo(22, 22); ctx.lineTo(106, 106);
            ctx.moveTo(106, 22); ctx.lineTo(22, 106);
            ctx.stroke();
            break;
        case 'triangle':
            ctx.beginPath();
            ctx.moveTo(64, 16); ctx.lineTo(112, 106); ctx.lineTo(16, 106);
            ctx.closePath(); ctx.stroke();
            break;
        case 'arrow':
            // Filled chevron pointing UP (rotated at runtime via material.rotation)
            ctx.beginPath();
            ctx.moveTo(64, 8); ctx.lineTo(114, 112); ctx.lineTo(64, 82); ctx.lineTo(14, 112);
            ctx.closePath(); ctx.fill();
            break;
        case 'ring':
            ctx.beginPath();
            ctx.arc(64, 64, 52, 0, Math.PI * 2);
            ctx.stroke();
            break;
    }
    tex = new THREE.CanvasTexture(canvas);
    glyphCache.set(kind, tex);
    return tex;
}

function makeGlyphSprite(kind: GlyphKind, size: number, renderOrder: number): THREE.Sprite {
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
        map: glyphTexture(kind), transparent: true, depthTest: false,
    }));
    sprite.scale.set(size, size, 1);
    sprite.renderOrder = renderOrder;
    sprite.userData.glyphKind = kind;
    return sprite;
}

function stateColor(state: TrackState): number {
    switch (state) {
        case TrackState.CONFIRMED: return C.TRACK_CONFIRMED;
        case TrackState.TENTATIVE: return C.TRACK_TENTATIVE;
        default: return C.TRACK_LOST;
    }
}

function glyphForState(state: TrackState): GlyphKind {
    switch (state) {
        case TrackState.CONFIRMED: return 'diamond';
        case TrackState.TENTATIVE: return 'square';
        default: return 'cross';
    }
}

function fmtRange(m: number): string {
    return m >= 1000 ? `${(m / 1000).toFixed(1)}km` : `${Math.round(m / 10) * 10}m`;
}

// ---------------------------------------------------------------------------

interface TrackMarker {
    root: THREE.Group;
    glyph: THREE.Sprite;
    ring: THREE.Sprite;      // pulsing intercept-warning ring
    label: THREE.Sprite;
    leader: THREE.Line;
    hit: THREE.Mesh;
    threatEma: number;       // smoothed 0..1 intercept verdict
    threatActive: boolean;   // hysteresis output
}

interface NodeMarker {
    root: THREE.Group;
    glyph: THREE.Sprite;
    label: THREE.Sprite;
}

export class HudOverlay {
    /** World-space overlay root (markers + dome statics). */
    readonly group = new THREE.Group();

    private domeStatics = new THREE.Group();
    private markers = new Map<string, TrackMarker>();
    private nodeMarkers = new Map<string, NodeMarker>();
    private edgeGroup = new THREE.Group();
    private arrows: THREE.Sprite[] = [];

    private hitGeo = new THREE.SphereGeometry(MARKER_SIZE * 1.2, 8, 6);

    private tmpDir = new THREE.Vector3();
    private tmpVel = new THREE.Vector3();
    private tmpPerp = new THREE.Vector3();
    private tmpNdc = new THREE.Vector3();
    private tmpCamSpace = new THREE.Vector3();
    private tmpMat = new THREE.Matrix4();

    constructor(scene: THREE.Scene, camera: THREE.Camera) {
        scene.add(this.group);
        this.group.add(this.domeStatics);
        this.buildDomeStatics();

        // Edge arrows are head-locked: children of the camera (the camera is
        // added to the scene by the SceneManager so its children render).
        camera.add(this.edgeGroup);
        for (let i = 0; i < H.MAX_EDGE_ARROWS; i++) {
            const arrow = makeGlyphSprite('arrow', 0.05, 8);
            arrow.visible = false;
            this.arrows.push(arrow);
            this.edgeGroup.add(arrow);
        }
    }

    get pickTargets(): THREE.Object3D[] {
        const targets: THREE.Object3D[] = [];
        this.markers.forEach(m => targets.push(m.hit));
        return targets;
    }

    setVisible(visible: boolean): void {
        this.group.visible = visible;
        this.edgeGroup.visible = visible;
    }

    /** Any track currently flagged as intercepting (post-hysteresis)? */
    get threatCount(): number {
        let n = 0;
        this.markers.forEach(m => { if (m.threatActive) n++; });
        return n;
    }

    isThreat(trackId: string): boolean {
        return this.markers.get(trackId)?.threatActive ?? false;
    }

    // ------------------------------------------------------------------ //
    // Dome statics: horizon ring + compass                                //
    // ------------------------------------------------------------------ //
    private buildDomeStatics(): void {
        // Horizon ring at eye level (distant objects sit on the true horizon)
        const ringPts: THREE.Vector3[] = [];
        for (let i = 0; i <= 64; i++) {
            const a = (i / 64) * Math.PI * 2;
            ringPts.push(new THREE.Vector3(Math.sin(a) * DOME_R, 0, -Math.cos(a) * DOME_R));
        }
        const ring = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(ringPts),
            new THREE.LineBasicMaterial({
                color: C.GRID_MAJOR, transparent: true, opacity: 0.55, depthTest: false,
            }));
        ring.renderOrder = 4;
        ring.frustumCulled = false;
        this.domeStatics.add(ring);

        // Compass ticks every 30°, taller at the cardinals, on the dome so
        // they sweep past like a real compass as the head turns.
        const tickPts: THREE.Vector3[] = [];
        for (let azDeg = 0; azDeg < 360; azDeg += 30) {
            const az = azDeg * DEG;
            const x = Math.sin(az) * DOME_R;
            const z = -Math.cos(az) * DOME_R;
            const h = azDeg % 90 === 0 ? 1.2 : 0.6;
            tickPts.push(new THREE.Vector3(x, 0, z), new THREE.Vector3(x, h, z));
        }
        const ticks = new THREE.LineSegments(
            new THREE.BufferGeometry().setFromPoints(tickPts),
            new THREE.LineBasicMaterial({
                color: C.GRID_MAJOR, transparent: true, opacity: 0.7, depthTest: false,
            }));
        ticks.renderOrder = 4;
        ticks.frustumCulled = false;
        this.domeStatics.add(ticks);

        const cardinals: Array<[string, number]> = [['N', 0], ['E', 90], ['S', 180], ['W', 270]];
        for (const [text, azDeg] of cardinals) {
            const az = azDeg * DEG;
            const sprite = makeLabelSprite();
            setLabelText(sprite, text, C.HUD_ACCENT);
            sprite.position.set(Math.sin(az) * DOME_R * 0.98, 2.1, -Math.cos(az) * DOME_R * 0.98);
            sprite.scale.set(2.4, 0.6, 1);
            sprite.renderOrder = 5;
            (sprite.material as THREE.SpriteMaterial).depthTest = false;
            this.domeStatics.add(sprite);
        }
    }

    // ------------------------------------------------------------------ //
    // Per-frame update                                                    //
    // ------------------------------------------------------------------ //
    /**
     * @param domeCenter head position while presenting; a fixed virtual head
     *        in flat mode (so the desktop orbit camera can inspect the dome).
     */
    update(camera: THREE.Camera, state: VRState, domeCenter: THREE.Vector3,
        timeMs: number, dt: number): void {
        if (!this.group.visible) return;

        const headingRad = (state.alignmentHeadingDeg ?? 0) * DEG;
        const cosH = Math.cos(headingRad);
        const sinH = Math.sin(headingRad);
        const flashOn = Math.floor(timeMs / 1000 * T.FLASH_HZ * 2) % 2 === 0;
        const emaAlpha = Math.min(1, dt / T.EMA_TAU_S);

        let obsEnu: [number, number, number] = [0, 0, 0];
        if (state.geoPose) {
            const o = VR_CONFIG.COORDINATE_ORIGIN;
            obsEnu = wgs84ToEnu(state.geoPose.lat, state.geoPose.lon, state.geoPose.alt,
                o.lat, o.lon, o.alt);
        }
        const obsVel = observerVelocityEnu(state.geoPose);

        // ENU delta → scene (E,U,−N) → yaw by alignment heading, in place.
        const toSceneDir = (dE: number, dN: number, dU: number, out: THREE.Vector3) => {
            const x = dE, y = dU, z = -dN;
            out.set(x * cosH + z * sinH, y, -x * sinH + z * cosH);
        };

        this.domeStatics.visible = state.showCompass;
        this.domeStatics.position.copy(domeCenter);
        this.domeStatics.rotation.set(0, headingRad, 0);

        // ---- track markers -------------------------------------------- //
        this.markers.forEach((m, id) => {
            if (!state.tracks[id]) {
                this.group.remove(m.root);
                (m.glyph.material as THREE.Material).dispose();
                (m.ring.material as THREE.Material).dispose();
                (m.leader.material as THREE.Material).dispose();
                m.leader.geometry.dispose();
                this.markers.delete(id);
            }
        });

        interface EdgeCandidate {
            track: Track; angle: number; dist: number; offscreen: boolean; threat: boolean;
        }
        const edgeCandidates: EdgeCandidate[] = [];
        this.tmpMat.copy(camera.matrixWorldInverse);

        for (const [id, track] of Object.entries(state.tracks)) {
            let m = this.markers.get(id);
            if (!m) {
                m = this.createTrackMarker(id);
                this.markers.set(id, m);
            }

            const dE = track.position[0] - obsEnu[0];
            const dN = track.position[1] - obsEnu[1];
            const dU = track.position[2] - obsEnu[2];
            toSceneDir(dE, dN, dU, this.tmpDir);
            const dist = this.tmpDir.length();
            if (dist < 1e-3) { m.root.visible = false; continue; }
            m.root.visible = true;
            this.tmpDir.divideScalar(dist);

            // Intercept assessment (headset-side CBDR) + hysteresis.
            const threat = assessIntercept(
                dE, dN, dU,
                track.velocity[0] - obsVel[0],
                track.velocity[1] - obsVel[1],
                track.velocity[2] - obsVel[2]);
            m.threatEma += ((threat.instant ? 1 : 0) - m.threatEma) * emaAlpha;
            if (m.threatActive && m.threatEma < T.EXIT_EMA) m.threatActive = false;
            else if (!m.threatActive && m.threatEma > T.ENTER_EMA) m.threatActive = true;

            // Depth cues: true placement inside the dome, size attenuation
            // with range outside it, far fade.
            const markerDist = Math.min(dist, DOME_R);
            m.root.position.copy(domeCenter).addScaledVector(this.tmpDir, markerDist);
            const att = Math.min(D.SIZE_MAX, Math.max(D.SIZE_MIN,
                Math.pow(D.REF_RANGE_M / Math.max(dist, 1), D.SIZE_EXP)));
            m.root.scale.setScalar((markerDist / DOME_R) * att);
            const glyphMat = m.glyph.material as THREE.SpriteMaterial;
            glyphMat.opacity = dist > D.FADE_START_M
                ? Math.max(D.MIN_OPACITY, 1 - (dist - D.FADE_START_M) / D.FADE_RANGE_M)
                : 1;

            const selected = state.selectedTrackId === id;
            const baseColor = selected ? C.TRACK_SELECTED : stateColor(track.state);
            const color = m.threatActive && flashOn ? THREAT_FLASH_COLOR : baseColor;
            const kind = glyphForState(track.state);
            if (m.glyph.userData.glyphKind !== kind) {
                glyphMat.map = glyphTexture(kind);
                m.glyph.userData.glyphKind = kind;
            }
            glyphMat.color.setHex(color);
            m.glyph.scale.setScalar(selected ? MARKER_SIZE * 1.35 : MARKER_SIZE);

            // Intercept ring: pulses while the warning is active.
            m.ring.visible = m.threatActive;
            if (m.threatActive) {
                const pulse = 1.7 + 0.3 * Math.sin(timeMs / 1000 * T.FLASH_HZ * Math.PI);
                m.ring.scale.setScalar(MARKER_SIZE * pulse);
                (m.ring.material as THREE.SpriteMaterial).color.setHex(color);
            }

            m.label.visible = state.showLabels;
            if (state.showLabels) {
                const alt = Math.round(track.position[2] / 10) * 10;
                const text = m.threatActive
                    ? `!! #${id} ${fmtRange(dist)} TCA ${threat.tcaS < 99 ? threat.tcaS.toFixed(0) + 's' : '--'}`
                    : `#${id} ${fmtRange(dist)} ${alt}m`;
                setLabelText(m.label, text, m.threatActive ? '#ff6060' : C.LABEL);
            }

            // Velocity leader: component of velocity perpendicular to the
            // sight line = the direction the designator will drift on the dome.
            toSceneDir(track.velocity[0], track.velocity[1], track.velocity[2], this.tmpVel);
            const speed = this.tmpVel.length();
            if (speed >= H.LEADER_MIN_SPEED_MS) {
                this.tmpPerp.copy(this.tmpVel)
                    .addScaledVector(this.tmpDir, -this.tmpVel.dot(this.tmpDir));
                if (this.tmpPerp.lengthSq() > 1e-6) {
                    this.tmpPerp.normalize().multiplyScalar(MARKER_SIZE * 1.7);
                    const attr = m.leader.geometry.getAttribute('position') as THREE.BufferAttribute;
                    attr.setXYZ(0, 0, 0, 0);
                    attr.setXYZ(1, this.tmpPerp.x, this.tmpPerp.y, this.tmpPerp.z);
                    attr.needsUpdate = true;
                    (m.leader.material as THREE.LineBasicMaterial).color.setHex(color);
                    m.leader.visible = true;
                } else {
                    m.leader.visible = false;
                }
            } else {
                m.leader.visible = false;
            }

            // Off-screen test in camera space (project() is ambiguous behind
            // the camera, so check z first).
            this.tmpCamSpace.copy(m.root.position).applyMatrix4(this.tmpMat);
            let offscreen: boolean;
            let angle: number;
            if (this.tmpCamSpace.z >= 0) {
                offscreen = true;
                angle = Math.atan2(this.tmpCamSpace.y, this.tmpCamSpace.x);
            } else {
                this.tmpNdc.copy(m.root.position).project(camera as THREE.PerspectiveCamera);
                offscreen = Math.abs(this.tmpNdc.x) > 0.95 || Math.abs(this.tmpNdc.y) > 0.95;
                angle = Math.atan2(this.tmpNdc.y, this.tmpNdc.x);
            }
            edgeCandidates.push({ track, angle, dist, offscreen, threat: m.threatActive });
        }

        // ---- edge arrows ---------------------------------------------- //
        // Priority: intercepting first, then selected, confirmed, nearest.
        const rank = (c: EdgeCandidate) =>
            (c.threat ? 0 : 4)
            + (state.selectedTrackId === c.track.track_id.toString() ? 0 : 2)
            + (c.track.state === TrackState.CONFIRMED ? 0 : 1);
        const off = edgeCandidates
            .filter(c => c.offscreen)
            .sort((a, b) => (rank(a) - rank(b)) || (a.dist - b.dist))
            .slice(0, H.MAX_EDGE_ARROWS);
        this.arrows.forEach((arrow, i) => {
            const c = off[i];
            if (!c) { arrow.visible = false; return; }
            arrow.visible = true;
            arrow.position.set(
                Math.cos(c.angle) * H.EDGE_RING_X,
                Math.sin(c.angle) * H.EDGE_RING_Y,
                -1);
            const mat = arrow.material as THREE.SpriteMaterial;
            mat.rotation = c.angle - Math.PI / 2;
            mat.color.setHex(c.threat && flashOn ? THREAT_FLASH_COLOR
                : state.selectedTrackId === c.track.track_id.toString()
                    ? C.TRACK_SELECTED : stateColor(c.track.state));
        });

        // ---- sensor-node markers -------------------------------------- //
        this.nodeMarkers.forEach((m, id) => {
            if (!state.nodes[id]) {
                this.group.remove(m.root);
                (m.glyph.material as THREE.Material).dispose();
                this.nodeMarkers.delete(id);
            }
        });
        for (const [id, node] of Object.entries(state.nodes)) {
            let m = this.nodeMarkers.get(id);
            if (!m) {
                const root = new THREE.Group();
                const glyph = makeGlyphSprite('triangle', MARKER_SIZE * 0.8, 6);
                const label = makeLabelSprite();
                label.position.set(0, -MARKER_SIZE * 0.9, 0);
                label.scale.set(LABEL_W * 0.8, LABEL_W * 0.2, 1);
                label.renderOrder = 7;
                (label.material as THREE.SpriteMaterial).depthTest = false;
                root.add(glyph, label);
                this.group.add(root);
                m = { root, glyph, label };
                this.nodeMarkers.set(id, m);
            }
            m.root.visible = state.showNodeMarkers;
            if (!m.root.visible) continue;
            const loc = node.location || [0, 0, 0];
            toSceneDir(loc[0] - obsEnu[0], loc[1] - obsEnu[1], loc[2] - obsEnu[2], this.tmpDir);
            const dist = this.tmpDir.length();
            if (dist < 1e-3) { m.root.visible = false; continue; }
            this.tmpDir.divideScalar(dist);
            const markerDist = Math.min(dist, DOME_R);
            m.root.position.copy(domeCenter).addScaledVector(this.tmpDir, markerDist);
            m.root.scale.setScalar(markerDist / DOME_R);
            (m.glyph.material as THREE.SpriteMaterial).color.setHex(
                node.status === NodeHealthStatus.HEALTHY ? C.NODE_HEALTHY : C.NODE_DEGRADED);
            m.label.visible = state.showLabels;
            if (state.showLabels) setLabelText(m.label, `${id} ${fmtRange(dist)}`, C.LABEL);
        }
    }

    private createTrackMarker(id: string): TrackMarker {
        const root = new THREE.Group();

        const glyph = makeGlyphSprite('diamond', MARKER_SIZE, 6);

        const ring = makeGlyphSprite('ring', MARKER_SIZE * 1.7, 5);
        ring.visible = false;

        const label = makeLabelSprite();
        label.position.set(0, -MARKER_SIZE * 1.1, 0);
        label.scale.set(LABEL_W, LABEL_W / 4, 1);
        label.renderOrder = 7;
        (label.material as THREE.SpriteMaterial).depthTest = false;

        const leaderGeo = new THREE.BufferGeometry();
        leaderGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
        const leader = new THREE.Line(leaderGeo, new THREE.LineBasicMaterial({
            color: C.TRACK_CONFIRMED, transparent: true, opacity: 0.9, depthTest: false,
        }));
        leader.renderOrder = 6;
        leader.frustumCulled = false;

        const hit = new THREE.Mesh(this.hitGeo);
        hit.visible = false;
        hit.userData.trackId = id;

        root.add(glyph, ring, label, leader, hit);
        this.group.add(root);
        return { root, glyph, ring, label, leader, hit, threatEma: 0, threatActive: false };
    }
}
