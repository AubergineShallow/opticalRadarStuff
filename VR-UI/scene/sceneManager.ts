/**
 * SceneManager — owns the renderer, the XR session, the transform chain and
 * the render loop.
 *
 * Two view modes:
 *
 * HUD (default, the AR/MR experience): the 1:1 scene geometry is HIDDEN and
 * scene/hudOverlay.ts draws target designators on a head-centered dome at
 * each track's true bearing/elevation (anchored via phone GNSS + compass —
 * see hudOverlay.ts). Sessions prefer 'immersive-ar' (passthrough) and fall
 * back to 'immersive-vr', where a ground grid + horizon give orientation.
 *
 * TABLETOP (CIC-style overview): transform chain
 *   scene └─ root (scale/yaw/anchor) └─ content (ENU metres, pan offset)
 * parked on a virtual table in front of the user's session-start position.
 */

import * as THREE from 'three';
import { VR_CONFIG } from '../constants';
import { enuToSceneXYZ } from '../geo';
import { VRState, VRStore } from '../store';
import { Entities, makeLabelSprite, setLabelText } from './entities';
import { HudOverlay } from './hudOverlay';
import { HudPanel } from '../hud/hudPanel';
import { ControllerInput } from '../input/controllers';

const C = VR_CONFIG.COLORS;

export type XRPreference = 'auto' | 'ar' | 'vr';

export class SceneManager {
    readonly renderer: THREE.WebGLRenderer;
    readonly scene: THREE.Scene;
    readonly camera: THREE.PerspectiveCamera;
    readonly root = new THREE.Group();
    readonly content = new THREE.Group();
    readonly entities: Entities;
    readonly overlay: HudOverlay;
    readonly hud: HudPanel;
    readonly input: ControllerInput;

    /** Physical drag offset of the table anchor (left-grip grab). */
    readonly grabOffset = new THREE.Vector3();
    private readonly tableAnchor = new THREE.Vector3(
        0, VR_CONFIG.TABLETOP.HEIGHT_M, -VR_CONFIG.TABLETOP.DISTANCE_M);
    private tableRing: THREE.Mesh;
    private groundGrid: THREE.Object3D;
    private background = new THREE.Color(C.BACKGROUND);
    private passthrough = false;

    // Flat-mode (non-XR) orbit camera state
    private orbit = { yawDeg: 0, pitchDeg: -35, dist: 2.5 };
    // Fixed "virtual head" the dome centers on in flat mode, so the desktop
    // orbit camera can inspect the HUD from outside.
    private flatHead = new THREE.Vector3(0, 1.6, 0);

    private dirty = { tracks: true, rays: true, voxels: true, nodes: true };
    private unsubStore: () => void;
    private lastFrameMs = 0;
    private tmpVec = new THREE.Vector3();

    constructor(private store: VRStore, private xrPref: XRPreference = 'auto') {
        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.setSize(window.innerWidth, window.innerHeight);
        this.renderer.xr.enabled = true;
        // Mobile-class GPU: let the runtime foveate aggressively.
        if (typeof (this.renderer.xr as any).setFoveation === 'function') {
            (this.renderer.xr as any).setFoveation(0.8);
        }
        document.body.appendChild(this.renderer.domElement);

        this.scene = new THREE.Scene();
        this.scene.background = this.background;

        this.camera = new THREE.PerspectiveCamera(
            70, window.innerWidth / window.innerHeight, 0.05, 50000);
        this.camera.position.set(0, 1.6, 1.5);
        // Camera must be in the scene graph: the overlay parents its
        // head-locked edge arrows to it.
        this.scene.add(this.camera);

        this.scene.add(this.root);
        this.root.add(this.content);

        this.buildGridAndCompass();
        this.entities = new Entities(this.content);
        this.overlay = new HudOverlay(this.scene, this.camera);

        // Table ring: fixed physical size, so it is a sibling of root (root is
        // scaled) and re-anchored every frame in applyModeTransform.
        this.tableRing = new THREE.Mesh(
            new THREE.RingGeometry(1.02, 1.06, 48),
            new THREE.MeshBasicMaterial({
                color: C.GRID_MAJOR, side: THREE.DoubleSide,
                transparent: true, opacity: 0.6,
            }));
        this.tableRing.rotation.x = -Math.PI / 2;
        this.scene.add(this.tableRing);

        // Ground reference for HUD mode in VR / flat fallback (passthrough
        // sessions see the real floor instead).
        this.groundGrid = new THREE.PolarGridHelper(
            VR_CONFIG.HUD.GROUND_GRID_RADIUS_M, 8, 3, 48, C.GRID_MAJOR, C.GRID);
        ((this.groundGrid as THREE.PolarGridHelper).material as THREE.Material).transparent = true;
        ((this.groundGrid as THREE.PolarGridHelper).material as THREE.Material).opacity = 0.35;
        this.groundGrid.position.y = 0.01;
        this.scene.add(this.groundGrid);

        this.hud = new HudPanel(this.scene, store);
        this.input = new ControllerInput(this.renderer, this.scene, store, this);

        this.unsubStore = store.subscribe((s, p) => {
            if (s.tracks !== p.tracks || s.trails !== p.trails
                || s.selectedTrackId !== p.selectedTrackId || s.showTrails !== p.showTrails) {
                this.dirty.tracks = true;
            }
            if (s.rays !== p.rays || s.showRays !== p.showRays) this.dirty.rays = true;
            if (s.voxels !== p.voxels || s.showVoxels !== p.showVoxels) this.dirty.voxels = true;
            if (s.nodes !== p.nodes) this.dirty.nodes = true;
        });

        this.renderer.xr.addEventListener('sessionstart', () => {
            const session: any = this.renderer.xr.getSession();
            // 'opaque' = VR; anything else ('alpha-blend'/'additive') = real
            // passthrough — drop the virtual sky so the real world shows.
            this.passthrough = !!session && session.environmentBlendMode !== 'opaque';
            this.scene.background = this.passthrough ? null : this.background;
        });
        this.renderer.xr.addEventListener('sessionend', () => {
            this.passthrough = false;
            this.scene.background = this.background;
        });

        window.addEventListener('resize', this.onResize);
        this.renderer.setAnimationLoop((t: number, frame?: any) => this.animate(t, frame));
    }

    // ------------------------------------------------------------------ //
    // XR session (AR/passthrough preferred, VR fallback)                  //
    // ------------------------------------------------------------------ //
    async startXR(): Promise<void> {
        const xr = (navigator as any).xr;
        if (!xr) throw new Error('WebXR not available in this browser');
        let mode: string = 'immersive-vr';
        if (this.xrPref === 'ar') {
            mode = 'immersive-ar';
        } else if (this.xrPref === 'auto') {
            const arOk = await xr.isSessionSupported('immersive-ar').catch(() => false);
            if (arOk) mode = 'immersive-ar';
        }
        const session = await xr.requestSession(mode, {
            optionalFeatures: ['local-floor', 'bounded-floor', 'hand-tracking'],
        });
        this.renderer.xr.setReferenceSpaceType('local-floor');
        await this.renderer.xr.setSession(session);
    }

    // ------------------------------------------------------------------ //
    // Static scenery (tabletop content)                                   //
    // ------------------------------------------------------------------ //
    private buildGridAndCompass(): void {
        const grid = new THREE.PolarGridHelper(
            VR_CONFIG.GRID_RADIUS_METERS, 8, 4, 64, C.GRID_MAJOR, C.GRID);
        (grid.material as THREE.Material).transparent = true;
        (grid.material as THREE.Material).opacity = 0.5;
        this.content.add(grid);

        // Compass letters at the grid edge. North = -Z in the scene frame.
        const R = VR_CONFIG.GRID_RADIUS_METERS + 60;
        const points: Array<[string, number, number]> = [
            ['N', 0, -R], ['E', R, 0], ['S', 0, R], ['W', -R, 0],
        ];
        for (const [text, x, z] of points) {
            const sprite = makeLabelSprite();
            setLabelText(sprite, text, C.HUD_ACCENT);
            sprite.position.set(x, 20, z);
            sprite.scale.set(160, 40, 1);
            this.content.add(sprite);
        }
    }

    // ------------------------------------------------------------------ //
    // Mode transform (every frame — cheap)                                //
    // ------------------------------------------------------------------ //
    private applyModeTransform(state: VRState): void {
        if (state.viewMode === 'TABLETOP') {
            this.root.visible = true;
            this.root.scale.setScalar(state.tabletopScale);
            this.root.rotation.set(0, THREE.MathUtils.degToRad(state.tabletopYawDeg), 0);
            this.root.position.copy(this.tableAnchor).add(this.grabOffset);

            const [cx, cy, cz] = enuToSceneXYZ(...state.tabletopCenterEnu);
            this.content.position.set(-cx, -cy, -cz);

            this.tableRing.visible = true;
            this.tableRing.position.copy(this.root.position);
            this.groundGrid.visible = false;
        } else {
            // HUD: the raw 1:1 geometry is hidden; hudOverlay draws the
            // designator dome instead.
            this.root.visible = false;
            this.tableRing.visible = false;
            this.groundGrid.visible = !this.passthrough;
        }
        this.overlay.setVisible(state.viewMode === 'HUD');
    }

    // ------------------------------------------------------------------ //
    // Actions used by the input layer                                     //
    // ------------------------------------------------------------------ //
    centerOnSelected(): boolean {
        const state = this.store.getState();
        if (state.selectedTrackId == null) return false;
        const track = state.tracks[state.selectedTrackId];
        if (!track) return false;
        state.setTabletopCenter(track.position);
        return true;
    }

    /** Capture the current compass heading as the HUD/world alignment. */
    alignToHeading(): boolean {
        const state = this.store.getState();
        const heading = state.geoPose?.heading_deg;
        if (heading == null || !isFinite(heading)) return false;
        state.setAlignmentHeading(heading);
        return true;
    }

    /** Pick targets for the controller ray, depending on the view mode. */
    getPickTargets(): THREE.Object3D[] {
        return this.store.getState().viewMode === 'HUD'
            ? this.overlay.pickTargets
            : this.entities.pickTargets;
    }

    /** Orbit-camera nudges for flat (non-XR) mode. */
    flatOrbit(dYawDeg: number, dPitchDeg: number, zoomFactor: number): void {
        this.orbit.yawDeg += dYawDeg;
        this.orbit.pitchDeg = Math.min(85, Math.max(-85, this.orbit.pitchDeg + dPitchDeg));
        this.orbit.dist = Math.min(50, Math.max(0.3, this.orbit.dist * zoomFactor));
    }

    // ------------------------------------------------------------------ //
    // Render loop                                                         //
    // ------------------------------------------------------------------ //
    private animate(timeMs: number, _frame?: any): void {
        const dt = this.lastFrameMs ? Math.min(0.1, (timeMs - this.lastFrameMs) / 1000) : 0.016;
        this.lastFrameMs = timeMs;

        const state = this.store.getState();

        // Auto-align once, when HUD mode first has a usable compass heading.
        if (state.viewMode === 'HUD' && state.alignmentHeadingDeg === null
            && state.geoPose && isFinite(state.geoPose.heading_deg)) {
            state.setAlignmentHeading(state.geoPose.heading_deg);
        }

        this.applyModeTransform(state);

        if (this.dirty.tracks) {
            this.dirty.tracks = false;
            this.entities.syncTracks(state.tracks, state.trails, state.selectedTrackId, state.showTrails);
        }
        if (this.dirty.rays) {
            this.dirty.rays = false;
            this.entities.syncRays(state.rays, state.showRays);
        }
        if (this.dirty.voxels) {
            this.dirty.voxels = false;
            this.entities.syncVoxels(state.voxels, state.showVoxels);
        }
        if (this.dirty.nodes) {
            this.dirty.nodes = false;
            this.entities.syncNodes(state.nodes);
        }

        this.input.update(dt);

        const presenting = this.renderer.xr.isPresenting;
        if (!presenting) {
            this.updateFlatCamera(state);
        }

        if (state.viewMode === 'HUD') {
            const domeCenter = presenting
                ? this.camera.getWorldPosition(this.tmpVec)
                : this.flatHead;
            this.overlay.update(this.camera, state, domeCenter, timeMs, dt);
        } else {
            this.entities.update(this.camera, state.tabletopScale, timeMs);
        }
        this.hud.update(this.camera, timeMs, presenting);

        this.renderer.render(this.scene, this.camera);
    }

    private updateFlatCamera(state: VRState): void {
        const target = state.viewMode === 'TABLETOP'
            ? this.tmpVec.copy(this.tableAnchor).add(this.grabOffset)
            : this.tmpVec.copy(this.flatHead);
        const yaw = THREE.MathUtils.degToRad(this.orbit.yawDeg);
        const pitch = THREE.MathUtils.degToRad(this.orbit.pitchDeg);
        const d = Math.max(this.orbit.dist, 0.3);
        this.camera.position.set(
            target.x + d * Math.cos(pitch) * Math.sin(yaw),
            target.y - d * Math.sin(pitch),
            target.z + d * Math.cos(pitch) * Math.cos(yaw));
        this.camera.lookAt(target);
    }

    private onResize = (): void => {
        this.camera.aspect = window.innerWidth / window.innerHeight;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(window.innerWidth, window.innerHeight);
    };

    dispose(): void {
        this.renderer.setAnimationLoop(null);
        this.unsubStore();
        window.removeEventListener('resize', this.onResize);
        this.renderer.dispose();
    }
}
