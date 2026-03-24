import { ScatterplotLayer, LineLayer, GridCellLayer, TextLayer, PolygonLayer, PathLayer } from '@deck.gl/layers';
import { COORDINATE_SYSTEM } from '@deck.gl/core';
import { UI_CONFIG, ROOM_CONFIG } from '../../constants';
import { NodeHealth, NodeHealthStatus, Ray, Track, Voxel } from '../../types';

// --- Helper for FOV ---
function getFOVPolygon(pos: [number, number], azimuth: number, fov: number, range: number) {
    const segments = 30;
    const points: [number, number][] = [pos];
    const startAngle = (azimuth - fov / 2) * (Math.PI / 180);
    const endAngle = (azimuth + fov / 2) * (Math.PI / 180);

    for (let i = 0; i <= segments; i++) {
        const theta = startAngle + (endAngle - startAngle) * (i / segments);
        points.push([
            pos[0] + Math.cos(theta) * range,
            pos[1] + Math.sin(theta) * range
        ]);
    }
    return points;
}

// --- Room Environment Layers ---
export function createRoomLayers() {
    const w = ROOM_CONFIG.WIDTH / 2;
    const d = ROOM_CONFIG.DEPTH / 2;

    // 1. Floor Polygon
    const floorLayer = new PolygonLayer({
        id: 'room-floor',
        data: [{
            contour: [
                [-w, -d], [w, -d], [w, d], [-w, d]
            ]
        }],
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getPolygon: (d: any) => d.contour,
        getFillColor: UI_CONFIG.COLORS.ROOM_FLOOR,
        stroked: false,
        pickable: false,
    });

    // 2. Grid Lines (Every 1 meter)
    const gridLines = [];
    // Vertical lines
    for (let x = -Math.floor(w); x <= Math.floor(w); x++) {
        gridLines.push({ path: [[x, -d], [x, d]], color: UI_CONFIG.COLORS.ROOM_GRID });
    }
    // Horizontal lines
    for (let y = -Math.floor(d); y <= Math.floor(d); y++) {
        gridLines.push({ path: [[-w, y], [w, y]], color: UI_CONFIG.COLORS.ROOM_GRID });
    }

    const gridLayer = new PathLayer({
        id: 'room-grid',
        data: gridLines,
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getPath: (d: any) => d.path,
        getColor: (d: any) => d.color,
        getWidth: 0.02, // 2cm wide lines
        widthUnits: 'meters',
        pickable: false
    });

    // 3. Wall Border
    const wallLayer = new PathLayer({
        id: 'room-walls',
        data: [{ path: [[-w, -d], [w, -d], [w, d], [-w, d], [-w, -d]] }],
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getPath: (d: any) => d.path,
        getColor: UI_CONFIG.COLORS.ROOM_WALLS,
        getWidth: 0.1, // 10cm thick walls
        widthUnits: 'meters',
        pickable: false
    });

    return [floorLayer, gridLayer, wallLayer];
}

// --- FOV Layer ---
export function createFOVLayer(data: NodeHealth[]) {
    return new PolygonLayer({
        id: 'fov-cones',
        data,
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getPolygon: (d: NodeHealth) => {
            // Default config if missing
            const { azimuth_deg, fov_deg, range_meters } = d.config || { azimuth_deg: 0, fov_deg: 60, range_meters: 5 };

            // Convert Geographic Azimuth (0=North, 90=East) to Math Angle (0=East, 90=North)
            // Math = 90 - Azimuth
            const mathAngle = 90 - azimuth_deg;
            return getFOVPolygon(d.location, mathAngle, fov_deg, range_meters);
        },
        getFillColor: [0, 255, 255, 30], // Increased opacity for visibility
        getLineColor: [0, 255, 255, 60],
        getLineWidth: 0.05,
        stroked: true,
        pickable: false,
    });
}

// --- Node Layer ---
interface NodeLayerProps {
    data: NodeHealth[];
    onSelectNode: (id: string) => void;
}

export function createNodeLayer(props: NodeLayerProps) {
    const { data, onSelectNode } = props;

    return new ScatterplotLayer({
        id: 'nodes',
        data,
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getPosition: (d: NodeHealth) => d.location,
        getFillColor: (d: NodeHealth) => d.status === NodeHealthStatus.HEALTHY
            ? UI_CONFIG.COLORS.NODE_HEALTHY
            : UI_CONFIG.COLORS.NODE_ISSUE,
        getRadius: UI_CONFIG.NODE_POINT_RADIUS,
        pickable: true,
        onClick: (info) => {
            if (info.object) {
                onSelectNode(info.object.node_id);
            }
        },
        updateTriggers: {
            getFillColor: [data]
        }
    });
}

// --- Ray Layer ---
interface RayLayerProps {
    data: Ray[];
    visible: boolean;
}

export function createRayLayer(props: RayLayerProps) {
    const { data, visible } = props;

    if (!visible) return null;

    return new LineLayer({
        id: 'rays',
        data,
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getSourcePosition: (d: Ray) => d.origin,
        getTargetPosition: (d: Ray) => [
            d.origin[0] + d.direction[0] * UI_CONFIG.RAY_LENGTH_METERS,
            d.origin[1] + d.direction[1] * UI_CONFIG.RAY_LENGTH_METERS
        ],
        getColor: UI_CONFIG.COLORS.RAY_DEFAULT,
        getWidth: 1, // Thinner rays for room scale
        widthUnits: 'pixels',
        pickable: false,
        updateTriggers: {
            data: [data.length]
        }
    });
}

// --- Voxel Layer (2D Grid) ---
interface VoxelLayerProps {
    data: Voxel[];
    visible: boolean;
}

export function createVoxelLayer(props: VoxelLayerProps) {
    const { data, visible } = props;

    if (!visible) return null;

    return new GridCellLayer({
        id: 'voxels',
        data,
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getPosition: (d: Voxel) => [d.x, d.y],
        getFillColor: (d: Voxel) => [
            (d.intensity / 255) * 255,
            255 - ((d.intensity / 255) * 255),
            0,
            d.intensity
        ],
        cellSize: UI_CONFIG.VOXEL_SIZE_METERS,
        pickable: true,
        material: false,
        updateTriggers: {
            getFillColor: [data]
        }
    });
}

// --- Track Layer ---
interface TrackLayerProps {
    data: Track[];
    onSelectTrack: (id: string) => void;
    selectedTrackId: string | null;
}

export function createTrackLayers(props: TrackLayerProps) {
    const { data, onSelectTrack, selectedTrackId } = props;

    const pointLayer = new ScatterplotLayer({
        id: 'track-points',
        data,
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getPosition: (d: Track) => d.position,
        getFillColor: (d: Track) => d.track_id.toString() === selectedTrackId
            ? [255, 255, 255]
            : UI_CONFIG.COLORS.TRACK_DEFAULT,
        getRadius: (d: Track) => d.track_id.toString() === selectedTrackId
            ? UI_CONFIG.TRACK_POINT_RADIUS * 1.2
            : UI_CONFIG.TRACK_POINT_RADIUS,
        pickable: true,
        onClick: (info) => {
            if (info.object) {
                onSelectTrack(info.object.track_id.toString());
            }
        },
        updateTriggers: {
            getPosition: [data],
            getFillColor: [selectedTrackId],
            getRadius: [selectedTrackId]
        }
    });

    const textLayer = new TextLayer({
        id: 'track-labels',
        data,
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getPosition: (d: Track) => [
            d.position[0],
            d.position[1] + UI_CONFIG.TRACK_POINT_RADIUS * 1.5
        ],
        getText: (d: Track) => `P-${d.track_id}`, // P for Person
        getSize: 12, // Smaller text
        getColor: UI_CONFIG.COLORS.TEXT_LABEL,
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'center',
        background: true,
        backgroundColor: [0, 0, 0, 150],
        backgroundPadding: [2, 1],
        updateTriggers: {
            getPosition: [data],
            getText: [data]
        }
    });

    return [pointLayer, textLayer];
}

// --- Track History Layer ---
interface TrackHistoryLayerProps {
    data: Track[];
    visible: boolean;
}

export function createTrackHistoryLayer(props: TrackHistoryLayerProps) {
    const { data, visible } = props;
    if (!visible) return null;

    const tracksWithHistory = data.filter(t => t.history && t.history.length > 1);

    return new PathLayer({
        id: 'track-history',
        data: tracksWithHistory,
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getPath: (d: Track) => d.history as [number, number][],
        getColor: () => [...UI_CONFIG.COLORS.TRACK_DEFAULT, 100] as [number, number, number, number],
        getWidth: 0.1, // 10cm wide
        widthUnits: 'meters',
        pickable: false,
        updateTriggers: {
            getPath: [data]
        }
    });
}

// --- Velocity Vector Layer ---
interface VelocityVectorLayerProps {
    data: Track[];
    visible: boolean;
}

export function createVelocityVectorLayer(props: VelocityVectorLayerProps) {
    const { data, visible } = props;
    if (!visible) return null;

    return new LineLayer({
        id: 'velocity-vectors',
        data,
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getSourcePosition: (d: Track) => d.position,
        getTargetPosition: (d: Track) => [
            d.position[0] + d.velocity[0],
            d.position[1] + d.velocity[1]
        ],
        getColor: [255, 255, 0, 200], // Yellow for velocity heading
        getWidth: 2,
        widthUnits: 'pixels',
        pickable: false,
        updateTriggers: {
            getSourcePosition: [data],
            getTargetPosition: [data]
        }
    });
}
