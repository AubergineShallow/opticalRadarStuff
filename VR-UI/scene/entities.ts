/**
 * Scene entities: three.js objects for tracks, trails, rays, voxels and
 * sensor nodes, all positioned in the ENU→scene frame (geo.ts) as children
 * of the content group the SceneManager owns.
 *
 * Performance rules (Steam Frame is a mobile-class GPU):
 *  - unlit materials only (MeshBasicMaterial / additive lines),
 *  - rays are ONE preallocated LineSegments, voxels are ONE InstancedMesh,
 *  - per-track objects are pooled in Maps and tolerate tracks vanishing
 *    between frames (full-replace convention),
 *  - every buffer is bounded by the VR_CONFIG.MAX_* caps.
 */

import * as THREE from 'three';
import { VR_CONFIG } from '../constants';
import { enuToSceneXYZ } from '../geo';
import {
    Track, Ray, Voxel, NodeHealth, NodeHealthStatus, TrackState, Vector3,
} from '../types';

const C = VR_CONFIG.COLORS;

// ---------------------------------------------------------------------------
// Label sprites (canvas-backed, billboarded, distance-scaled per frame)
// ---------------------------------------------------------------------------

interface LabelData {
    canvas: HTMLCanvasElement;
    ctx: CanvasRenderingContext2D;
    texture: THREE.CanvasTexture;
    text: string;
}

export function makeLabelSprite(): THREE.Sprite {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 64;
    const ctx = canvas.getContext('2d')!;
    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.SpriteMaterial({
        map: texture, transparent: true, depthTest: false,
    });
    const sprite = new THREE.Sprite(material);
    sprite.userData.label = { canvas, ctx, texture, text: '' } as LabelData;
    return sprite;
}

export function setLabelText(sprite: THREE.Sprite, text: string, color: string): void {
    const label = sprite.userData.label as LabelData;
    if (label.text === text) return;
    label.text = text;
    const { ctx, canvas } = label;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.font = 'bold 28px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
    const w = Math.min(canvas.width, ctx.measureText(text).width + 20);
    ctx.fillRect((canvas.width - w) / 2, 8, w, 48);
    ctx.fillStyle = color;
    ctx.fillText(text, canvas.width / 2, canvas.height / 2, canvas.width - 16);
    label.texture.needsUpdate = true;
}

function disposeLabel(sprite: THREE.Sprite): void {
    const label = sprite.userData.label as LabelData;
    label.texture.dispose();
    (sprite.material as THREE.SpriteMaterial).dispose();
}

// ---------------------------------------------------------------------------
// Per-track object pool
// ---------------------------------------------------------------------------

interface TrackObj {
    group: THREE.Group;
    body: THREE.Mesh;
    shell: THREE.Mesh;           // selection highlight
    hit: THREE.Mesh;             // invisible pick sphere for the controller ray
    velocity: THREE.Line;
    label: THREE.Sprite;
    trail: THREE.Line;
    trailPositions: Float32Array;
}

interface NodeObj {
    group: THREE.Group;
    body: THREE.Mesh;
    label: THREE.Sprite;
    lastSeen: number;
}

function stateColor(state: TrackState): number {
    switch (state) {
        case TrackState.CONFIRMED: return C.TRACK_CONFIRMED;
        case TrackState.TENTATIVE: return C.TRACK_TENTATIVE;
        default: return C.TRACK_LOST;
    }
}

function nodeStatusColor(status: NodeHealthStatus, stale: boolean): number {
    if (stale) return C.NODE_STALE;
    switch (status) {
        case NodeHealthStatus.HEALTHY: return C.NODE_HEALTHY;
        case NodeHealthStatus.DEGRADED: return C.NODE_DEGRADED;
        case NodeHealthStatus.FAILING: return C.NODE_FAILING;
        default: return C.NODE_OFFLINE;
    }
}

export class Entities {
    private trackObjs = new Map<string, TrackObj>();
    private nodeObjs = new Map<string, NodeObj>();

    private tracksGroup = new THREE.Group();
    private nodesGroup = new THREE.Group();
    private trailsGroup = new THREE.Group();

    private raysObj: THREE.LineSegments;
    private rayPositions: Float32Array;

    private voxelsMesh: THREE.InstancedMesh;

    // Shared geometries/materials
    private sphereGeo = new THREE.SphereGeometry(1, 16, 12);
    private shellGeo = new THREE.IcosahedronGeometry(1.6, 1);
    private hitGeo = new THREE.SphereGeometry(VR_CONFIG.TRACK_HIT_RADIUS_M, 8, 6);
    private nodeGeo = new THREE.OctahedronGeometry(VR_CONFIG.NODE_RADIUS_M);

    private tmpVec = new THREE.Vector3();
    private tmpCam = new THREE.Vector3();
    private tmpMatrix = new THREE.Matrix4();
    private tmpColor = new THREE.Color();
    private voxelCold = new THREE.Color(C.VOXEL_COLD);
    private voxelHot = new THREE.Color(C.VOXEL_HOT);

    constructor(private parent: THREE.Group) {
        parent.add(this.tracksGroup, this.nodesGroup, this.trailsGroup);

        // Rays: one preallocated LineSegments
        this.rayPositions = new Float32Array(VR_CONFIG.MAX_RENDER_RAYS * 6);
        const rayGeo = new THREE.BufferGeometry();
        rayGeo.setAttribute('position', new THREE.BufferAttribute(this.rayPositions, 3));
        rayGeo.setDrawRange(0, 0);
        this.raysObj = new THREE.LineSegments(rayGeo, new THREE.LineBasicMaterial({
            color: C.RAY, transparent: true, opacity: 0.3,
            blending: THREE.AdditiveBlending, depthWrite: false,
        }));
        this.raysObj.frustumCulled = false;
        parent.add(this.raysObj);

        // Voxels: one InstancedMesh
        const voxelGeo = new THREE.BoxGeometry(1, 1, 1);
        this.voxelsMesh = new THREE.InstancedMesh(
            voxelGeo,
            new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.45 }),
            VR_CONFIG.MAX_RENDER_VOXELS
        );
        this.voxelsMesh.count = 0;
        this.voxelsMesh.frustumCulled = false;
        parent.add(this.voxelsMesh);
    }

    /** Invisible pick spheres for controller-ray track selection. */
    get pickTargets(): THREE.Object3D[] {
        const targets: THREE.Object3D[] = [];
        this.trackObjs.forEach(o => targets.push(o.hit));
        return targets;
    }

    // ------------------------------------------------------------------ //
    // Tracks + trails                                                    //
    // ------------------------------------------------------------------ //
    syncTracks(
        tracks: Record<string, Track>,
        trails: Record<string, Vector3[]>,
        selectedTrackId: string | null,
        showTrails: boolean,
    ): void {
        // Remove pooled objects for vanished tracks (full-replace contract).
        this.trackObjs.forEach((obj, id) => {
            if (!tracks[id]) {
                this.tracksGroup.remove(obj.group);
                this.trailsGroup.remove(obj.trail);
                disposeLabel(obj.label);
                obj.trail.geometry.dispose();
                (obj.trail.material as THREE.Material).dispose();
                (obj.body.material as THREE.Material).dispose();
                (obj.velocity.material as THREE.Material).dispose();
                obj.velocity.geometry.dispose();
                this.trackObjs.delete(id);
            }
        });

        for (const [id, track] of Object.entries(tracks)) {
            let obj = this.trackObjs.get(id);
            if (!obj) {
                obj = this.createTrackObj(id);
                this.trackObjs.set(id, obj);
            }

            const [x, y, z] = enuToSceneXYZ(...track.position);
            obj.group.position.set(x, y, z);

            const radius = Math.min(
                VR_CONFIG.TRACK_MAX_RADIUS_M,
                Math.max(VR_CONFIG.TRACK_MIN_RADIUS_M,
                    track.physical_size ? track.physical_size * 2 : VR_CONFIG.TRACK_MIN_RADIUS_M)
            );
            obj.body.scale.setScalar(radius);
            obj.shell.scale.setScalar(radius);

            const selected = selectedTrackId === id;
            (obj.body.material as THREE.MeshBasicMaterial).color.setHex(
                selected ? C.TRACK_SELECTED : stateColor(track.state));
            obj.shell.visible = selected;

            // Velocity vector: position → position + v * VELOCITY_VECTOR_SECONDS
            const [vx, vy, vz] = enuToSceneXYZ(...track.velocity);
            const t = VR_CONFIG.VELOCITY_VECTOR_SECONDS;
            const vGeo = obj.velocity.geometry.getAttribute('position') as THREE.BufferAttribute;
            vGeo.setXYZ(0, 0, 0, 0);
            vGeo.setXYZ(1, vx * t, vy * t, vz * t);
            vGeo.needsUpdate = true;

            const alt = Math.round(track.position[2] / 10) * 10;
            setLabelText(obj.label, `#${id} ${alt}m`, C.LABEL);
            obj.label.position.set(0, radius + 25, 0);

            // Trail
            const trail = trails[id] || [];
            const n = Math.min(trail.length, VR_CONFIG.MAX_TRAIL_POINTS);
            for (let i = 0; i < n; i++) {
                const [tx, ty, tz] = enuToSceneXYZ(...trail[trail.length - n + i]);
                obj.trailPositions[i * 3] = tx;
                obj.trailPositions[i * 3 + 1] = ty;
                obj.trailPositions[i * 3 + 2] = tz;
            }
            const tAttr = obj.trail.geometry.getAttribute('position') as THREE.BufferAttribute;
            tAttr.needsUpdate = true;
            obj.trail.geometry.setDrawRange(0, n);
            obj.trail.visible = showTrails && n > 1;
        }
    }

    private createTrackObj(id: string): TrackObj {
        const group = new THREE.Group();

        const body = new THREE.Mesh(this.sphereGeo,
            new THREE.MeshBasicMaterial({ color: C.TRACK_CONFIRMED }));
        const shell = new THREE.Mesh(this.shellGeo,
            new THREE.MeshBasicMaterial({ color: C.TRACK_SELECTED, wireframe: true, transparent: true, opacity: 0.7 }));
        shell.visible = false;

        const hit = new THREE.Mesh(this.hitGeo);
        hit.visible = false;
        hit.userData.trackId = id;

        const vGeo = new THREE.BufferGeometry();
        vGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
        const velocity = new THREE.Line(vGeo,
            new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.8 }));
        velocity.frustumCulled = false;

        const label = makeLabelSprite();

        group.add(body, shell, hit, velocity, label);
        this.tracksGroup.add(group);

        const trailPositions = new Float32Array(VR_CONFIG.MAX_TRAIL_POINTS * 3);
        const trailGeo = new THREE.BufferGeometry();
        trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPositions, 3));
        trailGeo.setDrawRange(0, 0);
        const trail = new THREE.Line(trailGeo,
            new THREE.LineBasicMaterial({ color: C.TRAIL, transparent: true, opacity: 0.5 }));
        trail.frustumCulled = false;
        this.trailsGroup.add(trail);

        return { group, body, shell, hit, velocity, label, trail, trailPositions };
    }

    // ------------------------------------------------------------------ //
    // Rays                                                               //
    // ------------------------------------------------------------------ //
    syncRays(rays: Ray[], show: boolean): void {
        this.raysObj.visible = show && rays.length > 0;
        if (!this.raysObj.visible) {
            this.raysObj.geometry.setDrawRange(0, 0);
            return;
        }
        const n = Math.min(rays.length, VR_CONFIG.MAX_RENDER_RAYS);
        for (let i = 0; i < n; i++) {
            const ray = rays[i];
            const [ox, oy, oz] = enuToSceneXYZ(...ray.origin);
            const [dx, dy, dz] = enuToSceneXYZ(...ray.direction);
            const L = VR_CONFIG.RAY_LENGTH_METERS;
            const base = i * 6;
            this.rayPositions[base] = ox;
            this.rayPositions[base + 1] = oy;
            this.rayPositions[base + 2] = oz;
            this.rayPositions[base + 3] = ox + dx * L;
            this.rayPositions[base + 4] = oy + dy * L;
            this.rayPositions[base + 5] = oz + dz * L;
        }
        const attr = this.raysObj.geometry.getAttribute('position') as THREE.BufferAttribute;
        attr.needsUpdate = true;
        this.raysObj.geometry.setDrawRange(0, n * 2);
    }

    // ------------------------------------------------------------------ //
    // Voxels                                                             //
    // ------------------------------------------------------------------ //
    syncVoxels(voxels: Voxel[], show: boolean): void {
        this.voxelsMesh.visible = show && voxels.length > 0;
        if (!this.voxelsMesh.visible) {
            this.voxelsMesh.count = 0;
            return;
        }
        const n = Math.min(voxels.length, VR_CONFIG.MAX_RENDER_VOXELS);
        const size = VR_CONFIG.VOXEL_SIZE_METERS * 0.9;
        for (let i = 0; i < n; i++) {
            const v = voxels[i];
            const [x, y, z] = enuToSceneXYZ(v.x, v.y, v.z);
            this.tmpMatrix.makeScale(size, size, size);
            this.tmpMatrix.setPosition(x, y, z);
            this.voxelsMesh.setMatrixAt(i, this.tmpMatrix);
            const heat = Math.min(1, Math.max(0, v.intensity / 255));
            this.tmpColor.lerpColors(this.voxelCold, this.voxelHot, heat);
            this.voxelsMesh.setColorAt(i, this.tmpColor);
        }
        this.voxelsMesh.count = n;
        this.voxelsMesh.instanceMatrix.needsUpdate = true;
        if (this.voxelsMesh.instanceColor) this.voxelsMesh.instanceColor.needsUpdate = true;
    }

    // ------------------------------------------------------------------ //
    // Sensor nodes                                                       //
    // ------------------------------------------------------------------ //
    syncNodes(nodes: Record<string, NodeHealth>): void {
        this.nodeObjs.forEach((obj, id) => {
            if (!nodes[id]) {
                this.nodesGroup.remove(obj.group);
                disposeLabel(obj.label);
                (obj.body.material as THREE.Material).dispose();
                this.nodeObjs.delete(id);
            }
        });

        for (const [id, node] of Object.entries(nodes)) {
            let obj = this.nodeObjs.get(id);
            if (!obj) {
                const group = new THREE.Group();
                const body = new THREE.Mesh(this.nodeGeo,
                    new THREE.MeshBasicMaterial({ color: C.NODE_HEALTHY }));
                const label = makeLabelSprite();
                label.position.set(0, VR_CONFIG.NODE_RADIUS_M + 20, 0);
                group.add(body, label);
                this.nodesGroup.add(group);
                obj = { group, body, label, lastSeen: node.last_seen };
                this.nodeObjs.set(id, obj);
            }
            obj.lastSeen = node.last_seen;
            const [x, y, z] = enuToSceneXYZ(...(node.location || [0, 0, 0] as Vector3));
            obj.group.position.set(x, y, z);
            setLabelText(obj.label, id, C.LABEL);
            this.recolorNode(obj, node.status);
        }
        this.nodeStatuses = Object.fromEntries(
            Object.values(nodes).map(n => [n.node_id, n.status]));
    }

    private nodeStatuses: Record<string, NodeHealthStatus> = {};

    private recolorNode(obj: NodeObj, status: NodeHealthStatus): void {
        const stale = (Date.now() / 1000 - obj.lastSeen) > VR_CONFIG.STALE_NODE_SECONDS;
        (obj.body.material as THREE.MeshBasicMaterial).color.setHex(
            nodeStatusColor(status, stale));
    }

    // ------------------------------------------------------------------ //
    // Per-frame maintenance                                              //
    // ------------------------------------------------------------------ //
    private lastStaleCheck = 0;

    /**
     * Called every frame: distance-scales labels so they stay legible at any
     * tabletop scale / world range, and re-evaluates node staleness at 1 Hz.
     */
    update(camera: THREE.Camera, contentScale: number, nowMs: number): void {
        camera.getWorldPosition(this.tmpCam);

        const scaleLabel = (sprite: THREE.Sprite) => {
            sprite.getWorldPosition(this.tmpVec);
            const dist = this.tmpVec.distanceTo(this.tmpCam);
            // ~2.5° apparent width, clamped, expressed in local (pre-scale) units.
            const w = Math.min(4000, Math.max(0.5, dist * 0.045)) / contentScale;
            sprite.scale.set(w, w / 4, 1);
        };

        let labelBudget = VR_CONFIG.MAX_LABELS;
        this.trackObjs.forEach(obj => {
            obj.label.visible = labelBudget-- > 0;
            if (obj.label.visible) scaleLabel(obj.label);
        });
        this.nodeObjs.forEach(obj => {
            obj.label.visible = labelBudget-- > 0;
            if (obj.label.visible) scaleLabel(obj.label);
        });

        if (nowMs - this.lastStaleCheck > 1000) {
            this.lastStaleCheck = nowMs;
            this.nodeObjs.forEach((obj, id) => {
                const status = this.nodeStatuses[id] ?? NodeHealthStatus.OFFLINE;
                this.recolorNode(obj, status);
            });
        }
    }
}
