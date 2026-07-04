/**
 * Controller-first input (the Steam Frame ships with game-controller-style
 * Frame Controllers; they expose the standard WebXR `xr-standard` gamepad
 * mapping: buttons[0]=trigger, [1]=squeeze/grip, [3]=stick click,
 * [4]=A/X, [5]=B/Y; axes[2]/[3]=thumbstick).
 *
 * In XR:
 *   RIGHT  trigger…select pointed track   A…HUD ⇄ TABLETOP mode
 *          B…align to compass (HUD) / reset (tabletop)
 *          stick…rotate + zoom tabletop   stick-click…center on selection
 *   LEFT   (HUD mode)      trigger…labels  X…compass/horizon  Y…node markers
 *          (tabletop mode) trigger…trails  X…rays             Y…voxels
 *          grip(hold)…grab-drag the table stick…pan       stick-click…panel
 *
 * Flat (desktop) fallback: standard Gamepad API mapping + mouse orbit +
 * keyboard (r/v/t layers, m mode, c center, Esc deselect) so the frontend is
 * fully drivable during development without a headset.
 */

import * as THREE from 'three';
import { VR_CONFIG } from '../constants';
import { VRStore } from '../store';
import type { SceneManager } from '../scene/sceneManager';

const DEADZONE = 0.15;
const ROTATE_DEG_PER_S = 70;
const SCALE_RATE = 1.6;             // e-fold per second of full stick
const PAN_SCENE_M_PER_S = 0.6;      // pan speed on the table surface

interface HandState {
    controller: THREE.Group;
    inputSource: any;               // XRInputSource
    prev: boolean[];
}

function axis(gp: any, i: number): number {
    const v = gp?.axes?.[i] ?? 0;
    return Math.abs(v) < DEADZONE ? 0 : v;
}

function pressed(gp: any, i: number): boolean {
    return !!gp?.buttons?.[i]?.pressed;
}

export class ControllerInput {
    private hands: Record<'left' | 'right', HandState | null> = { left: null, right: null };
    private raycaster = new THREE.Raycaster();
    private pointerLine: THREE.Line;
    private cursor: THREE.Mesh;
    private grab: { startPos: THREE.Vector3; startOffset: THREE.Vector3 } | null = null;
    private prevFlatButtons: boolean[] = [];
    private mouseDown = false;

    private tmpPos = new THREE.Vector3();
    private tmpDir = new THREE.Vector3();
    private tmpQuat = new THREE.Quaternion();

    constructor(
        private renderer: THREE.WebGLRenderer,
        private scene: THREE.Scene,
        private store: VRStore,
        private sm: SceneManager,
    ) {
        // XR controller objects (three keeps their poses updated).
        for (let i = 0; i < 2; i++) {
            const controller = renderer.xr.getController(i);
            controller.addEventListener('connected', (event: any) => {
                const src = event.data;
                const hand = src.handedness === 'left' ? 'left' : 'right';
                this.hands[hand] = { controller, inputSource: src, prev: [] };
                if (hand === 'right') controller.add(this.pointerLine);
            });
            controller.addEventListener('disconnected', () => {
                for (const hand of ['left', 'right'] as const) {
                    if (this.hands[hand]?.controller === controller) this.hands[hand] = null;
                }
            });
            scene.add(controller);
        }

        // Right-hand pointer ray + hover cursor
        const lineGeo = new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, -5),
        ]);
        this.pointerLine = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({
            color: VR_CONFIG.COLORS.POINTER, transparent: true, opacity: 0.6,
        }));
        this.cursor = new THREE.Mesh(
            new THREE.SphereGeometry(0.01, 8, 6),
            new THREE.MeshBasicMaterial({ color: VR_CONFIG.COLORS.POINTER }));
        this.cursor.visible = false;
        scene.add(this.cursor);

        window.addEventListener('keydown', this.onKeyDown);
        const el = renderer.domElement;
        el.addEventListener('pointerdown', () => { this.mouseDown = true; });
        window.addEventListener('pointerup', () => { this.mouseDown = false; });
        el.addEventListener('pointermove', (e: PointerEvent) => {
            if (this.mouseDown && !renderer.xr.isPresenting) {
                this.sm.flatOrbit(-e.movementX * 0.3, -e.movementY * 0.2, 1);
            }
        });
        el.addEventListener('wheel', (e: WheelEvent) => {
            if (!renderer.xr.isPresenting) this.sm.flatOrbit(0, 0, Math.exp(e.deltaY * 0.001));
        }, { passive: true });
    }

    update(dt: number): void {
        if (this.renderer.xr.isPresenting) {
            this.updateXR(dt);
        } else {
            this.updateFlatGamepad(dt);
        }
    }

    // ------------------------------------------------------------------ //
    // XR path                                                             //
    // ------------------------------------------------------------------ //
    private updateXR(dt: number): void {
        const state = this.store.getState();
        const right = this.hands.right;
        const left = this.hands.left;

        if (right?.inputSource?.gamepad) {
            const gp = right.inputSource.gamepad;
            const was = right.prev;

            // Hover cursor (also primes the pick for the trigger action)
            const hit = this.pickFromController(right.controller);
            this.cursor.visible = !!hit;
            if (hit) this.cursor.position.copy(hit.point);

            if (pressed(gp, 0) && !was[0]) {                    // trigger: select
                if (hit) {
                    state.selectTrack(hit.trackId);
                    this.pulse(right, 0.6, 60);
                } else {
                    state.selectTrack(null);
                }
            }
            if (pressed(gp, 3) && !was[3]) {                    // stick click: center
                if (this.sm.centerOnSelected()) this.pulse(right, 0.4, 40);
            }
            if (pressed(gp, 4) && !was[4]) {                    // A: cycle mode
                state.setViewMode(state.viewMode === 'TABLETOP' ? 'HUD' : 'TABLETOP');
                this.pulse(right, 0.4, 40);
            }
            if (pressed(gp, 5) && !was[5]) {                    // B: align / reset
                if (state.viewMode === 'HUD') {
                    if (this.sm.alignToHeading()) this.pulse(right, 0.5, 80);
                } else {
                    state.resetTabletop();
                    this.sm.grabOffset.set(0, 0, 0);
                    this.pulse(right, 0.5, 80);
                }
            }

            if (state.viewMode === 'TABLETOP') {
                const rx = axis(gp, 2);
                if (rx) state.setTabletopYaw(state.tabletopYawDeg + rx * ROTATE_DEG_PER_S * dt);
                const ry = axis(gp, 3);                          // stick up = zoom in
                if (ry) state.setTabletopScale(state.tabletopScale * Math.exp(-ry * SCALE_RATE * dt));
            }

            right.prev = gp.buttons.map((b: any) => b.pressed);
        } else {
            this.cursor.visible = false;
        }

        if (left?.inputSource?.gamepad) {
            const gp = left.inputSource.gamepad;
            const was = left.prev;

            // Layer toggles are mode-aware: HUD declutter vs tabletop layers.
            const hudMode = state.viewMode === 'HUD';
            if (pressed(gp, 0) && !was[0]) state.toggleLayer(hudMode ? 'labels' : 'trails'); // trigger
            if (pressed(gp, 4) && !was[4]) state.toggleLayer(hudMode ? 'compass' : 'rays');  // X
            if (pressed(gp, 5) && !was[5]) state.toggleLayer(hudMode ? 'nodes' : 'voxels');  // Y
            if (pressed(gp, 3) && !was[3]) state.toggleHud();                                // stick click

            // Grip hold: grab-drag the table anchor
            if (state.viewMode === 'TABLETOP' && pressed(gp, 1)) {
                left.controller.getWorldPosition(this.tmpPos);
                if (!this.grab) {
                    this.grab = {
                        startPos: this.tmpPos.clone(),
                        startOffset: this.sm.grabOffset.clone(),
                    };
                } else {
                    this.sm.grabOffset.copy(this.grab.startOffset)
                        .add(this.tmpPos).sub(this.grab.startPos);
                }
            } else {
                this.grab = null;
            }

            // Stick: pan the tabletop (view-relative, compensating table yaw)
            if (state.viewMode === 'TABLETOP') {
                const px = axis(gp, 2);
                const py = axis(gp, 3);
                if (px || py) {
                    const yaw = THREE.MathUtils.degToRad(state.tabletopYawDeg);
                    const speed = (PAN_SCENE_M_PER_S / state.tabletopScale) * dt;
                    const forward = -py;
                    const dE = (px * Math.cos(yaw) + forward * Math.sin(yaw)) * speed;
                    const dN = (-px * Math.sin(yaw) + forward * Math.cos(yaw)) * speed;
                    const [e, n, u] = state.tabletopCenterEnu;
                    state.setTabletopCenter([e + dE, n + dN, u]);
                }
            }

            left.prev = gp.buttons.map((b: any) => b.pressed);
        }
    }

    private pickFromController(controller: THREE.Group):
        { trackId: string; point: THREE.Vector3 } | null {
        controller.getWorldPosition(this.tmpPos);
        controller.getWorldQuaternion(this.tmpQuat);
        this.tmpDir.set(0, 0, -1).applyQuaternion(this.tmpQuat);
        this.raycaster.set(this.tmpPos, this.tmpDir);
        this.raycaster.far = 100;
        const hits = this.raycaster.intersectObjects(this.sm.getPickTargets(), false);
        if (hits.length === 0) return null;
        return { trackId: hits[0].object.userData.trackId, point: hits[0].point };
    }

    private pulse(hand: HandState, intensity: number, ms: number): void {
        try {
            hand.inputSource?.gamepad?.hapticActuators?.[0]?.pulse(intensity, ms);
        } catch { /* haptics are best-effort */ }
    }

    // ------------------------------------------------------------------ //
    // Flat fallback: standard gamepad                                     //
    // ------------------------------------------------------------------ //
    private updateFlatGamepad(dt: number): void {
        const pads = (navigator.getGamepads ? navigator.getGamepads() : []) || [];
        const gp = Array.from(pads).find(p => p && p.connected);
        if (!gp) return;
        const state = this.store.getState();
        const was = this.prevFlatButtons;

        // Left stick: orbit. Right stick: pan (compass-relative: up = north).
        this.sm.flatOrbit(-axis(gp, 0) * 120 * dt, -axis(gp, 1) * 90 * dt, 1);
        const px = axis(gp, 2), py = axis(gp, 3);
        if ((px || py) && state.viewMode === 'TABLETOP') {
            const speed = (PAN_SCENE_M_PER_S / state.tabletopScale) * dt;
            const [e, n, u] = state.tabletopCenterEnu;
            state.setTabletopCenter([e + px * speed, n + (-py) * speed, u]);
        }
        // Triggers: zoom the tabletop
        const zoomIn = gp.buttons[7]?.value ?? 0;
        const zoomOut = gp.buttons[6]?.value ?? 0;
        if (zoomIn || zoomOut) {
            state.setTabletopScale(state.tabletopScale * Math.exp((zoomIn - zoomOut) * SCALE_RATE * dt));
        }

        const just = (i: number) => pressed(gp, i) && !was[i];
        const hudMode = state.viewMode === 'HUD';
        if (just(0)) this.cycleSelection(+1);                    // A
        if (just(1)) state.selectTrack(null);                    // B
        if (just(2)) state.toggleLayer(hudMode ? 'compass' : 'rays');   // X
        if (just(3)) state.toggleLayer(hudMode ? 'nodes' : 'voxels');   // Y
        if (just(4)) state.toggleLayer(hudMode ? 'labels' : 'trails');  // LB
        if (just(5)) state.setViewMode(hudMode ? 'TABLETOP' : 'HUD');   // RB
        if (just(8)) state.toggleHud();                          // Back
        if (just(9)) { state.resetTabletop(); this.sm.grabOffset.set(0, 0, 0); } // Start
        if (just(11)) this.sm.centerOnSelected();                // right stick click

        this.prevFlatButtons = gp.buttons.map(b => b.pressed);
    }

    private cycleSelection(step: number): void {
        const state = this.store.getState();
        const ids = Object.keys(state.tracks).sort((a, b) => Number(a) - Number(b));
        if (ids.length === 0) return;
        const idx = state.selectedTrackId != null ? ids.indexOf(state.selectedTrackId) : -1;
        state.selectTrack(ids[(idx + step + ids.length) % ids.length]);
    }

    // ------------------------------------------------------------------ //
    // Keyboard (dev convenience; mirrors NEW-UI-V2 where it makes sense)  //
    // ------------------------------------------------------------------ //
    private onKeyDown = (e: KeyboardEvent): void => {
        const state = this.store.getState();
        switch (e.key) {
            case 'r': state.toggleLayer('rays'); break;
            case 'v': state.toggleLayer('voxels'); break;
            case 't': state.toggleLayer('trails'); break;
            case 'k': state.toggleLayer('compass'); break;
            case 'n': state.toggleLayer('nodes'); break;
            case 'l': state.toggleLayer('labels'); break;
            case 'a': this.sm.alignToHeading(); break;
            case 'm': state.setViewMode(state.viewMode === 'TABLETOP' ? 'HUD' : 'TABLETOP'); break;
            case 'c': this.sm.centerOnSelected(); break;
            case 'h': state.toggleHud(); break;
            case 'Tab': this.cycleSelection(e.shiftKey ? -1 : +1); e.preventDefault(); break;
            case 'Escape': state.selectTrack(null); break;
            case '+': case '=': state.setTabletopScale(state.tabletopScale * 1.25); break;
            case '-': case '_': state.setTabletopScale(state.tabletopScale / 1.25); break;
        }
    };
}
