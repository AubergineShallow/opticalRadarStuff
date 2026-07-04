import { TileLayer } from '@deck.gl/geo-layers';
import { BitmapLayer, ScatterplotLayer, LineLayer, ColumnLayer, TextLayer, PathLayer } from '@deck.gl/layers';
import { COORDINATE_SYSTEM } from '@deck.gl/core';
import { UI_CONFIG } from '../../constants';
import { NodeHealth, NodeHealthStatus, Ray, Track, Vector3, Voxel } from '../../types';

// Map a node's health status to a fill colour. Previously only HEALTHY vs
// not-healthy was distinguished (green/red); a monitoring operator needs to tell
// DEGRADED and OFFLINE apart at a glance.
function nodeStatusColor(status: NodeHealthStatus): [number, number, number] {
    switch (status) {
        case NodeHealthStatus.HEALTHY: return UI_CONFIG.COLORS.NODE_HEALTHY;
        case NodeHealthStatus.DEGRADED: return [255, 200, 0];
        case NodeHealthStatus.FAILING: return [255, 130, 0];
        case NodeHealthStatus.OFFLINE: return [120, 120, 120];
        default: return UI_CONFIG.COLORS.NODE_ISSUE;
    }
}

// --- Base Map Layer ---
export function createBaseMapLayer() {
    return new TileLayer({
        id: 'base-map',
        data: 'https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
        minZoom: 0,
        maxZoom: 19,
        tileSize: 256,
        renderSubLayers: (props) => {
            // @ts-ignore - TileLayer types can be tricky
            const { boundingBox } = props.tile;

            return new BitmapLayer(props, {
                data: null,
                image: props.data,
                bounds: [boundingBox[0][0], boundingBox[0][1], boundingBox[1][0], boundingBox[1][1]]
            });
        },
        pickable: false,
    });
}

// --- Node Layer ---
interface NodeLayerProps {
    data: NodeHealth[];
    onSelectNode: (id: string) => void;
    selectedNodeId: string | null;
}

export function createNodeLayer(props: NodeLayerProps) {
    const { data, onSelectNode, selectedNodeId } = props;

    return new ScatterplotLayer({
        id: 'nodes',
        data,
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getPosition: (d: NodeHealth) => d.location,
        getFillColor: (d: NodeHealth) => nodeStatusColor(d.status),
        getRadius: (d: NodeHealth) => d.node_id === selectedNodeId
            ? UI_CONFIG.NODE_POINT_RADIUS * 2
            : UI_CONFIG.NODE_POINT_RADIUS,
        // White ring marks the selected node so map and sensor list agree.
        stroked: true,
        getLineColor: (d: NodeHealth) => d.node_id === selectedNodeId
            ? [255, 255, 255, 255]
            : [0, 0, 0, 0],
        getLineWidth: (d: NodeHealth) => d.node_id === selectedNodeId ? 2 : 0,
        lineWidthUnits: 'pixels',
        pickable: true,
        onClick: (info) => {
            if (info.object) {
                onSelectNode(info.object.node_id);
            }
        },
        updateTriggers: {
            getFillColor: [data],
            getRadius: [selectedNodeId],
            getLineColor: [selectedNodeId],
            getLineWidth: [selectedNodeId]
        }
    });
}

// --- Track Motion-Trail Layer ---
interface TrailDatum {
    track_id: number;
    path: Vector3[];
    cluster_id?: string;
}

interface TrailLayerProps {
    data: TrailDatum[];
    visible: boolean;
    selectedTrackId: string | null;
}

export function createTrailLayer(props: TrailLayerProps) {
    const { data, visible, selectedTrackId } = props;

    if (!visible) return null;

    const isSelected = (d: TrailDatum) => d.track_id.toString() === selectedTrackId;

    return new PathLayer({
        id: 'track-trails',
        data,
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getPath: (d: TrailDatum) => d.path,
        // The selected track's history reads brighter and wider so the eye can
        // follow the one path that matters among many faded ones.
        getColor: (d: TrailDatum) => isSelected(d) ? [255, 210, 60, 220] : [255, 165, 0, 100],
        getWidth: (d: TrailDatum) => isSelected(d) ? 4 : 2,
        widthMinPixels: 1.5,
        capRounded: true,
        jointRounded: true,
        pickable: false,
        updateTriggers: {
            getPath: [data],
            getColor: [selectedTrackId],
            getWidth: [selectedTrackId]
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
            d.origin[1] + d.direction[1] * UI_CONFIG.RAY_LENGTH_METERS,
            d.origin[2] + d.direction[2] * UI_CONFIG.RAY_LENGTH_METERS
        ],
        getColor: UI_CONFIG.COLORS.RAY_DEFAULT,
        getWidth: 2,
        pickable: false,
        updateTriggers: {
            data: [data.length] // Optimization: Only rebuild if count changes (for mock data)
        }
    });
}

// --- Voxel Layer ---
interface VoxelLayerProps {
    data: Voxel[];
    visible: boolean;
}

export function createVoxelLayer(props: VoxelLayerProps) {
    const { data, visible } = props;

    if (!visible) return null;

    return new ColumnLayer({
        id: 'voxels',
        data,
        coordinateSystem: COORDINATE_SYSTEM.METER_OFFSETS,
        coordinateOrigin: UI_CONFIG.COORDINATE_ORIGIN,
        getPosition: (d: Voxel) => [d.x, d.y],
        getElevation: (d: Voxel) => d.z,
        // Gradient from Green (low) to Red (high) based on intensity
        getFillColor: (d: Voxel) => [
            (d.intensity / 255) * 255,
            255 - ((d.intensity / 255) * 255),
            0,
            d.intensity // Alpha maps to intensity
        ],
        radius: UI_CONFIG.VOXEL_SIZE_METERS / 2,
        diskResolution: 4, // Square columns for efficiency
        elevationScale: 1,
        pickable: true,
        material: false, // Flat shading for performance
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
            ? [255, 200, 0] // Highlight color
            : UI_CONFIG.COLORS.TRACK_DEFAULT,
        getRadius: (d: Track) => d.track_id.toString() === selectedTrackId 
            ? UI_CONFIG.TRACK_POINT_RADIUS * 1.5 
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
        getPosition: (d: Track) => [d.position[0], d.position[1], d.position[2] + UI_CONFIG.TRACK_POINT_RADIUS * 2],
        getText: (d: Track) => `T-${d.track_id}`,
        getSize: 14,
        getColor: UI_CONFIG.COLORS.TEXT_LABEL,
        getAngle: 0,
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'center',
        background: true,
        getBackgroundColor: [0, 0, 0, 150], // backgroundColor is deprecated in deck.gl 9
        backgroundPadding: [4, 2],
        updateTriggers: {
            getPosition: [data],
            getText: [data]
        }
    });

    return [pointLayer, textLayer];
}
