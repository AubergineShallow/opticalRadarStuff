import React, { useState, useMemo } from 'react';
import DeckGL from '@deck.gl/react';
import { useAppStore } from '../../store';
import { UI_CONFIG, ROOM_CONFIG } from '../../constants';

// Layer Factories
import {
    createNodeLayer,
    createRayLayer,
    createVoxelLayer,
    createTrackLayers,
    createRoomLayers,
    createFOVLayer,
    createTrackHistoryLayer,
    createVelocityVectorLayer
} from './Layers';

export default function VisualizationMap() {
    const {
        tracks, rays, voxels, nodes,
        showRays, showVoxels,
        selectTrack, selectNode, selectedTrackId
    } = useAppStore();

    // Force strict 2D top-down view
    const [viewState, setViewState] = useState({
        ...UI_CONFIG.INITIAL_VIEW_STATE,
        pitch: 0,
        bearing: 0
    });

    // Memoize static room layers so they are not recreated every render
    const roomLayers = useMemo(() => createRoomLayers(), []);

    // --- LAYERS ---
    const layers = [
        // Room Environment (Floor, Grid, Walls)
        ...roomLayers,

        // FOV Cones (Below nodes, above floor)
        createFOVLayer(Object.values(nodes)),

        createNodeLayer({
            data: Object.values(nodes),
            onSelectNode: selectNode
        }),
        createRayLayer({
            data: rays,
            visible: showRays
        }),
        createVoxelLayer({
            data: voxels,
            visible: showVoxels
        }),
        createTrackHistoryLayer({
            data: Object.values(tracks),
            visible: true
        }),
        createVelocityVectorLayer({
            data: Object.values(tracks),
            visible: true // Always show velocity vectors for now
        }),
        ...createTrackLayers({
            data: Object.values(tracks),
            onSelectTrack: selectTrack,
            selectedTrackId: selectedTrackId
        })
    ].filter(Boolean);

    return (
        <div className="relative w-full h-full bg-black">
            <DeckGL
                viewState={viewState}
                controller={{
                    dragRotate: false,
                    touchRotate: false,
                    keyboard: {
                        moveSpeed: 5, // Slower keyboard pan for room scale
                        rotateSpeedX: 0,
                        rotateSpeedY: 0
                    },
                    doubleClickZoom: true,
                    scrollZoom: true,
                    dragPan: true
                }}
                layers={layers}
                onViewStateChange={(params: any) => {
                    setViewState({
                        ...params.viewState,
                        pitch: 0,
                        bearing: 0
                    });
                }}
                getTooltip={({ object }: any) => object && (
                    object.track_id ? `Person ${object.track_id}` :
                        object.node_id ? `Sensor ${object.node_id}` :
                            object.intensity ? `Voxel: ${object.intensity}` : null
                )}
                style={{ width: '100%', height: '100%' }}
            />

            {/* Scale/Orientation hint */}
            <div className="absolute bottom-4 right-4 text-xs text-gray-500 font-mono pointer-events-none text-right">
                <div className="mb-1 text-white">ROOM MONITOR: {ROOM_CONFIG.WIDTH}m x {ROOM_CONFIG.DEPTH}m</div>
                <div className="opacity-70">SCALE: 1 GRID = 1 METER</div>
            </div>
        </div>
    );
}