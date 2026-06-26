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

    // Filter data based on active cluster
    const filteredTracks = activeClusterId
        ? Object.values(tracks).filter(t => t.cluster_id === activeClusterId || !t.cluster_id)
        : Object.values(tracks);

    const filteredRays = activeClusterId
        ? rays.filter(r => r.cluster_id === activeClusterId || !r.cluster_id)
        : rays;

    const filteredVoxels = activeClusterId
        ? voxels.filter(v => v.cluster_id === activeClusterId || !v.cluster_id)
        : voxels;
    const layers = [
        // Base Map (Offline Support)
        createBaseMapLayer(),

        createNodeLayer({
            data: Object.values(nodes),
            onSelectNode: selectNode
        }),
        createRayLayer({
            data: filteredRays,
            visible: showRays
        }),
        createVoxelLayer({
            data: filteredVoxels,
            visible: showVoxels
        }),
        ...createTrackLayers({
            data: filteredTracks,
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