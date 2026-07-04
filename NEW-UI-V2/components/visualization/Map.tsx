import React, { useState, useMemo, useEffect } from 'react';
import DeckGL from '@deck.gl/react';
import { useAppStore } from '../../store';
import { UI_CONFIG } from '../../constants';
import { ViewStateChangeParameters, FlyToInterpolator, LinearInterpolator } from '@deck.gl/core';

// Layer Factories
import {
    createNodeLayer,
    createRayLayer,
    createVoxelLayer,
    createTrackLayers,
    createTrailLayer,
    createBaseMapLayer
} from './Layers';

export default function VisualizationMap() {
    const {
        tracks, trails, rays, voxels, nodes,
        showRays, showVoxels, showHistory, is3DMode,
        selectTrack, selectNode, selectedTrackId, selectedNodeId,
        activeClusterId, focusRequest
    } = useAppStore();

    const [viewState, setViewState] = useState(UI_CONFIG.INITIAL_VIEW_STATE);

    // 2D/3D toggle: flatten to a top-down view in 2D, restore the oblique tilt
    // in 3D. Keeps the current centre/zoom so the toggle doesn't jump the camera.
    useEffect(() => {
        setViewState(prev => ({
            ...prev,
            pitch: is3DMode ? 60 : 0,
            transitionDuration: 400,
            transitionInterpolator: new LinearInterpolator(['pitch']),
        }));
    }, [is3DMode]);

    // Camera focus requests (centre-on-track/node buttons, C hotkey). seq in the
    // dep list means focusing the same target twice still re-flies the camera.
    useEffect(() => {
        if (!focusRequest) return;
        setViewState(prev => ({
            ...prev,
            latitude: focusRequest.latitude,
            longitude: focusRequest.longitude,
            transitionDuration: 700,
            transitionInterpolator: new FlyToInterpolator(),
        }));
    }, [focusRequest?.seq]);

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

    // Build trail paths for the visible tracks only (respects the domain filter),
    // dropping single-point trails that would render as nothing.
    const trailsArr = useMemo(
        () => tracksArr
            .map(t => ({
                track_id: t.track_id,
                cluster_id: t.cluster_id,
                path: trails[t.track_id.toString()] || []
            }))
            .filter(d => d.path.length >= 2),
        [tracksArr, trails]
    );

    const layers = useMemo(() => [
        createBaseMapLayer(),
        createNodeLayer({ data: nodesArr, onSelectNode: selectNode, selectedNodeId }),
        createRayLayer({ data: raysArr, visible: showRays }),
        createVoxelLayer({ data: voxelsArr, visible: showVoxels }),
        createTrailLayer({ data: trailsArr, visible: showHistory, selectedTrackId }),
        ...createTrackLayers({
            data: tracksArr,
            onSelectTrack: selectTrack,
            selectedTrackId: selectedTrackId
        }),
    ].filter(Boolean), [
        nodesArr, tracksArr, raysArr, voxelsArr, trailsArr,
        showRays, showVoxels, showHistory, selectedTrackId, selectedNodeId,
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
                    // Explicit undefined checks: track_id 0 and intensity 0 are
                    // valid values that a truthiness test would silently drop.
                    object.track_id !== undefined ? `Track ${object.track_id}` :
                    object.node_id !== undefined ? `Node ${object.node_id}` :
                    object.intensity !== undefined ? `Voxel Intensity: ${object.intensity}` : null
                )}
                style={{ width: '100%', height: '100%' }}
            />

            {/* Sits above the connection pill (which owns bottom-4 right-4 in App) */}
            <div className="absolute bottom-12 right-4 text-[10px] text-gray-600 font-mono pointer-events-none">
                ENU ORIGIN: {UI_CONFIG.COORDINATE_ORIGIN.join(', ')}
            </div>
        </div>
    );
}
