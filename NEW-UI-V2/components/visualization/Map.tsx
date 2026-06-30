import React, { useState, useMemo } from 'react';
import DeckGL from '@deck.gl/react';
import { useAppStore } from '../../store';
import { UI_CONFIG } from '../../constants';
import { ViewStateChangeParameters } from '@deck.gl/core';

// Layer Factories
import { 
    createNodeLayer, 
    createRayLayer, 
    createVoxelLayer, 
    createTrackLayers, 
    createBaseMapLayer 
} from './Layers';

export default function VisualizationMap() {
    const {
        tracks, rays, voxels, nodes,
        showRays, showVoxels,
        selectTrack, selectNode, selectedTrackId
    } = useAppStore();

    const [viewState, setViewState] = useState(UI_CONFIG.INITIAL_VIEW_STATE);

    // Stabilise Object.values()
    const nodesArr  = useMemo(() => Object.values(nodes),  [nodes]);
    const tracksArr = useMemo(() => Object.values(tracks), [tracks]);

    // --- LAYERS ---
    const layers = useMemo(() => [
        // Base Map (Offline Support)
        createBaseMapLayer(),

        createNodeLayer({
            data: nodesArr,
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
        ...createTrackLayers({
            data: tracksArr,
            onSelectTrack: selectTrack,
            selectedTrackId: selectedTrackId
        })
    ].filter(Boolean), [nodesArr, tracksArr, rays, voxels, showRays, showVoxels, selectedTrackId, selectTrack, selectNode]);

    return (
        <div className="relative w-full h-full bg-black">
            <DeckGL
                viewState={viewState}
                controller={true}
                layers={layers}
                onViewStateChange={(params: ViewStateChangeParameters) => {
                    setViewState(params.viewState as any);
                }}
                getTooltip={({ object }) => object && (
                    object.track_id ? `Track ${object.track_id}` :
                    object.node_id ? `Node ${object.node_id}` :
                    object.intensity ? `Voxel Intensity: ${object.intensity}` : null
                )}
                style={{ width: '100%', height: '100%' }}
            />
            
            {/* Compass / Orientation hint could go here */}
            <div className="absolute bottom-4 right-4 text-xs text-gray-500 font-mono pointer-events-none">
                ENU ORIGIN: {UI_CONFIG.COORDINATE_ORIGIN.join(', ')}
            </div>
        </div>
    );
}