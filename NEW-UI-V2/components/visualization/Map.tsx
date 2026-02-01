import React, { useState } from 'react';
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

    // --- LAYERS ---
    const layers = [
        // Base Map (Offline Support)
        createBaseMapLayer(),

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
        ...createTrackLayers({
            data: Object.values(tracks),
            onSelectTrack: selectTrack,
            selectedTrackId: selectedTrackId
        })
    ].filter(Boolean);

    return (
        <div className="relative w-full h-full bg-black">
            <DeckGL
                initialViewState={viewState}
                controller={true}
                layers={layers}
                onViewStateChange={(params: ViewStateChangeParameters) => {
                    // @ts-ignore - ViewState handling can be loose in DeckGL types
                    setViewState(params.viewState);
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