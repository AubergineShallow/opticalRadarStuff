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
        selectTrack, selectNode, selectedTrackId,
        activeClusterId
    } = useAppStore();

    const [viewState, setViewState] = useState(UI_CONFIG.INITIAL_VIEW_STATE);

    // Filter every wire object by the active domain (P3.6). activeClusterId === null
    // is a deliberate "show all" admin toggle; items without a cluster_id (mock data,
    // or not yet stamped by the backend) are always shown.
    const inActiveCluster = useMemo(() => {
        return (item: { cluster_id?: string }) =>
            activeClusterId === null ||
            item.cluster_id === undefined ||
            item.cluster_id === activeClusterId;
    }, [activeClusterId]);

    // Object.values() allocates a new array on every call, so memoise it separately
    // — otherwise the outer layers memo sees a new reference every render and never
    // benefits from memoisation (P3.4).
    const nodesArr = useMemo(
        () => Object.values(nodes).filter(inActiveCluster),
        [nodes, inActiveCluster]
    );
    const tracksArr = useMemo(
        () => Object.values(tracks).filter(inActiveCluster),
        [tracks, inActiveCluster]
    );
    const raysArr = useMemo(() => rays.filter(inActiveCluster), [rays, inActiveCluster]);
    const voxelsArr = useMemo(() => voxels.filter(inActiveCluster), [voxels, inActiveCluster]);

    const layers = useMemo(() => [
        createBaseMapLayer(),
        createNodeLayer({ data: nodesArr, onSelectNode: selectNode }),
        createRayLayer({ data: raysArr, visible: showRays }),
        createVoxelLayer({ data: voxelsArr, visible: showVoxels }),
        ...createTrackLayers({
            data: tracksArr,
            onSelectTrack: selectTrack,
            selectedTrackId: selectedTrackId
        }),
    ].filter(Boolean), [
        nodesArr, tracksArr, raysArr, voxelsArr,
        showRays, showVoxels, selectedTrackId,
        selectTrack, selectNode
    ]);

    return (
        <div className="relative w-full h-full bg-black">
            <DeckGL
                viewState={viewState}        // controlled — not initialViewState (P3.4)
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
