---
name: ui-development
description: Develop, modify, and verify the NEW-UI-V2 React/deck.gl/zustand operator frontend — architecture and store conventions, WebSocket message wiring, deck.gl layers, keyboard shortcuts, mock mode, the esbuild syntax check, and the full browser runtime-preview workflow that works despite having no node_modules.
---

# NEW-UI-V2 Frontend Development

React 19 + deck.gl + zustand, in `NEW-UI-V2\`. **There is no package.json /
node_modules in the repo**: no `tsc`, no vite build, no npm test. The browser
resolves bare imports at runtime from esm.sh via the importmap in `index.html`.
Verification is (1) esbuild syntax checks and (2) a real browser preview — both
below.

## Architecture

| File | Role |
|---|---|
| `index.tsx` / `App.tsx` | bootstrap; picks mock vs WebSocket mode from `?mock=true` URL param |
| `constants.ts` | `UI_CONFIG` (view state, `COORDINATE_ORIGIN` — **must match server `reference.*`**, colors, ray length) and `Env.WS_URL` (`ws://localhost:5000/ws` — matches server `server.ws_port`) |
| `types.ts` | wire types (Track, NodeHealth, SystemStatus, ClusterInfo…) — keep in sync with server broadcast payload keys |
| `store.ts` | zustand `AppState`: tracks/rays/voxels/nodes/system/calibration/clusters, selection ids, layer toggles (`showRays/showVoxels/showHistory/is3DMode`), `trails` (bounded `MAX_TRAIL_POINTS = 60`, pruned for vanished tracks), `focusRequest` |
| `hooks.ts` | `useWebSocket` (connect/reconnect/dispatch) + `useMockData` (simulated scene) |
| `components/HUD.tsx` | HUD shell + global keyboard shortcuts |
| `components/hud/*` | panels: TopBar (cluster/domain dropdown, create), SensorList (health dots, STALE, CALIB, Locate), TargetList (track states), TrackDetail (speed/heading/confidence/ENU/velocity/"Est. Size" = `physical_size`), NodeDetail (fps/cpu/temp/ip/last-seen), SystemHealth (FPS/TRACKS/VOXELS), LayerControls |
| `components/visualization/Map.tsx` | DeckGL canvas; `is3DMode`→pitch 60/0; consumes `focusRequest` via FlyToInterpolator |
| `components/visualization/Layers.ts` | layer factories: `createBaseMapLayer` (CartoDB dark tiles), `createNodeLayer`, `createTrailLayer` (PathLayer, gated `showHistory`), `createRayLayer` (LineLayer, `showRays`), `createVoxelLayer` (ColumnLayer, `showVoxels`), `createTrackLayers` (Scatterplot + TextLayer) |

WS message → store dispatch (in `hooks.ts` onmessage switch): `TRACK_UPDATE`→
`setTracks`, `VOXEL_UPDATE`→`setVoxels`, `RAY_UPDATE`→`setRays`, `NODE_UPDATE`→
`updateNode` (accepts object OR array — server batches), `SYSTEM_STATUS`→
`updateSystemStatus` + `setCalibration`, `CLUSTER_UPDATE`→`setClusters` +
`setPendingNodes`.

## Conventions that MUST be preserved (each fixed a real bug)

1. **Selection lives in the store** (`selectedTrackId`/`selectedNodeId` +
   `selectTrack`/`selectNode`). Never keep component-local selection state — the
   HUD once had a local `selectedNodeId` while the map wrote to the store, and
   map↔list selection silently desynced.
2. **Camera fly-to uses the `focusRequest` seq pattern**: `requestFocus(lat, lon)`
   bumps `seq`; Map reacts to seq changes with FlyToInterpolator. Repeat requests
   to the same coords must still fly (that's what seq is for) — don't "optimize"
   it away.
3. **Trails are bounded**: `MAX_TRAIL_POINTS = 60` per track, appended in
   `setTracks`, pruned when a track vanishes. Any new accumulating collection in
   the store needs the same treatment (`quality-standards`).
4. **Reconnect logic in `useWebSocket`**: exponential backoff
   `RECONNECT_BASE_MS=500` → `RECONNECT_MAX_MS=10000`, re-subscribes to the
   active room on reconnect, flushes the buffered command queue (commands sent
   while disconnected are queued, not dropped). `onclose` owns reconnection;
   intentional teardown sets a flag so unmount doesn't trigger a reconnect.
   Effect deps are `[url, enabled]` — setters are pulled via
   `useAppStore.getState()` inside handlers to avoid resubscribe churn. Keep all
   of this if you touch the hook.
5. **Keyboard shortcuts** (HUD.tsx keydown): `r` rays, `v` voxels, `t` trails
   (history), `p` 2D/3D, `c` fly to selected, `Esc` deselect. Update this list
   and LayerControls together.
6. **Track list is full-replace per frame** (server sends the complete list; no
   per-track delete events) — UI logic must tolerate tracks disappearing between
   frames.
7. Beware falsy-zero traps: `track_id` can be `0` (a real tooltip bug once) —
   test with `!= null`, not truthiness.

## Mock mode

Open with `?mock=true` → `App.tsx` skips the WebSocket and `useMockData`
generates a simulated scene (sensors, moving tracks, rays, ~1 Hz heartbeats so
nodes don't show STALE). Voxels are NOT mocked — `setVoxels` is never called in
`useMockData`, so the voxel layer stays empty in sim mode. This is frontend-only
— the server is not involved. The status pill shows RUN SIM MODE / GO LIVE
links to switch.

## Verification workflow

### Level 1 — esbuild syntax check (every edited file, seconds)

```bash
cd NEW-UI-V2 && npx esbuild --log-level=warning components/HUD.tsx > /dev/null
```
(PowerShell: same command but redirect with `> $null`.) The loader is inferred
from the `.ts`/`.tsx` extension — do NOT add a bare `--loader=tsx` alongside a
file argument; that errors ("loader without extension only applies when reading
from stdin"). This is transform-only: it catches syntax errors, NOT type errors
— there is no typechecking in this repo. Do not claim "types check".

### Level 2 — real browser preview (required for store/layer/WS changes)

Bundle app code only, leave bare imports to the browser importmap (esm.sh):

```bash
cd NEW-UI-V2
npx esbuild index.tsx --bundle --format=esm \
  --outfile=<PREVIEW_DIR>/dist/index.js \
  --external:react --external:react-dom --external:react-dom/client \
  --external:zustand --external:lucide-react \
  --external:@deck.gl/react --external:@deck.gl/core \
  --external:@deck.gl/layers --external:@deck.gl/geo-layers \
  --jsx=automatic
```

Then in `<PREVIEW_DIR>`: copy `index.html`, keep its `<script type="importmap">`
block, remove the vite/plugin-react importmap entries and the `/index.css` link,
point the script tag at `./dist/index.js`. Serve it: the project's
`.claude/launch.json` defines a `python -m http.server` config on port 8123 —
**it points at a SESSION-SPECIFIC scratchpad path that will be stale; rebuild
your own `<PREVIEW_DIR>` and update launch.json's directory before use.** Then
`preview_start`, navigate to `http://localhost:8123/?mock=true`.

Caveats (learned the hard way):
- `preview_screenshot` often times out on the animated WebGL canvas — verify via
  `preview_eval` DOM queries and `preview_console_logs` instead.
- Mock mode exercises rendering/store wiring; to test live-WS paths run the real
  server + sim swarm (`run-and-debug-server`) and load without `?mock=true`.
- esm.sh needs network access; first load is slow (CDN fetch).

## Adding UI features — pattern

New data on screen: server broadcast key → `types.ts` → `hooks.ts` case →
store slice + setter → panel/layer consumes via `useAppStore` selector. New
layer: factory in `Layers.ts`, gate behind a store toggle, register toggle in
LayerControls + shortcut in HUD.tsx. Follow existing factories (they take plain
data + callbacks; no store access inside Layers.ts).

## Sibling frontend: VR-UI (WebXR)

`VR-UI\` is a second, WebXR frontend (Steam Frame reference hardware) —
plain TypeScript + three.js + zustand/vanilla, NO React. It consumes the
same WS broadcast plus a GEO_POSE feed from the `vr_companion_android`
phone app. Its `types.ts` mirrors this UI's — **change wire types in both**.
Same verification workflow as above (esbuild check; preview bundle with
`--external:three --external:zustand --external:zustand/vanilla`; probe via
`window.__vrDebug.store.getState()` / `.sm`), and unlike deck.gl its canvas
usually survives `preview_screenshot`. Full architecture: `VR-UI\README.md`.

## Related skills

`run-and-debug-server` (the WS payloads and ports this UI consumes),
`geometry-conventions` (COORDINATE_ORIGIN contract), `validate-changes`
(definition of done for UI work).
