# Frontend and UI (NEW-UI-V2)

## Overview
The `NEW-UI-V2` directory contains the modern React-based frontend for visualizing multi-domain tracking and telemetry.

## State Management

- **Zustand Store:** Global application state, including multi-cluster configurations, is managed centrally in `store.ts` using the Zustand library.
- **Cluster Filtering:** Elements on the map (nodes, tracks, etc.) are filtered dynamically on the client side. The application verifies that the `activeClusterId` property in the store matches the `cluster_id` property of the data entity before rendering.

## Real-Time Data Precomputation

- **WebSocket Hooks (`hooks.ts`):**
  - To maintain rendering performance under high update rates, complex coordinate conversions (e.g., ENU to LLA) and physics math (e.g., speed/heading derivations) are precomputed immediately upon receiving WebSocket messages.
  - This avoids re-calculating intensive math inside React render cycles for components like `TargetList` or `SensorList`.

## Visualization (deck.gl)

- **Map Rendering (`components/visualization/Map.tsx`):**
  - Deck.gl layers re-render rapidly. To prevent continuous, unnecessary layer rebuilds during user interactions like panning, the raw tracking arrays (`Object.values(nodes)` and `Object.values(tracks)`) must be stabilized.
  - This stabilization is achieved using custom `useMemo` hooks before these arrays are passed into the deck.gl layers array.

## Global Broadcasting

- **Status and Metrics:** System-wide metrics gathered by the `MetricsCollector` (such as active track counts and backend processing times) are aggregated and broadcast globally to all connected clients via the `SYSTEM_STATUS` WebSocket message.
- **Node Locations:** In `server_main.py`, the `_broadcast_state` method injects the physical location of nodes into the `NODE_UPDATE` payload by resolving it through `RayBuilder.get_camera_position(node_id)`.

## Code Health Conventions
- **Logging:** When finalizing code changes in the frontend, leftover `console.log` statements must be removed. However, `console.error` and `console.warn` should be preserved for meaningful error reporting in production.

## Verification
- To verify build integrity for the frontend, execute `npm run build` from within the `NEW-UI-V2/` directory. Ensure `node_modules` are installed or the environment has internet access to install them prior to building.