import { TileLayer } from '@deck.gl/geo-layers';
import { BitmapLayer, ScatterplotLayer, LineLayer, ColumnLayer, TextLayer } from '@deck.gl/layers';
import { COORDINATE_SYSTEM } from '@deck.gl/core';
import { UI_CONFIG } from '../../constants';
import { NodeHealth, NodeHealthStatus, Ray, Track, Voxel } from '../../types';

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
        backgroundColor: [0, 0, 0, 150],
        backgroundPadding: [4, 2],
        updateTriggers: {
            getPosition: [data],
            getText: [data]
        }
    });

    return [pointLayer, textLayer];
}
