# VR-UI — OpticalRadar AR/MR HUD Frontend

WebXR frontend for the OpticalRadar tracking server, targeting **Valve's
Steam Frame** as the reference headset/ecosystem. The primary experience is
an **augmented-reality HUD**: you look at the real sky through passthrough
and tracked objects are overlaid at their true bearing and elevation as
target designators — diamond/box reticles with range/altitude labels,
velocity leaders, off-screen direction arrows, and a world-aligned compass
and horizon. A CIC-style tabletop miniature remains as a secondary mode, and
a flat desktop fallback exists for development.

Plain TypeScript + [three.js](https://threejs.org) + zustand/vanilla — **no
React, no build step, no node_modules**: bare imports resolve at runtime
from esm.sh via the importmap in `index.html`, exactly like NEW-UI-V2.

```
 EDGE NODES ──UDP──▶ SERVER (code/server) ──ws://…:5000/ws──▶ VR-UI (this)
                                                                 ▲
             Android phone (vr_companion_android "GeoTether")────┘
             GNSS fix + true heading over the tether, ws://phone:8790
```

The Steam Frame has **no GNSS**, so world anchoring uses a tethered Android
phone running the GeoTether companion app (USB tether or hotspot). Track/
ray/voxel/node data comes from the normal server WebSocket broadcast —
**no server changes were needed**.

## View modes

| Mode | What it is | Anchoring |
|---|---|---|
| `HUD` (default) | AR/MR overlay: target designators at each track's TRUE direction, constant angular size, true range on the label; compass + horizon; edge arrows for off-screen tracks | phone GNSS fix + compass heading |
| `TABLETOP` | Miniature of the ENU scene on a virtual table 1.2 m in front of you (default 1:1000; rotate/zoom/pan/grab) | none needed |

**Why designators on a dome instead of 1:1 geometry:** a 2 km drone rendered
at true scale is an invisible dot. HUD mode draws markers on a head-centered
20 m annotation dome (comfortable vergence for far-field AR) in the exact
direction of the target; truth (range, altitude, speed) lives in the label
and the data panel. This is standard far-field AR annotation practice.

**Alignment procedure**: stand still, hold the phone level and pointing the
way you face, press **B** (right controller) or `a` on a keyboard. The
compass heading at that moment yaws the overlay so scene-north = true north;
your GNSS position becomes the ray origin for all designator directions.
Re-align any time; auto-aligns once when the first usable heading arrives.
The panel shows `AR HUD — UNALIGNED (press B)` until then.

## Intercept warning (computed on the headset)

`threat.ts` runs a classic CBDR check per track per frame — *constant
bearing, decreasing range*: from relative position/velocity it derives
closing speed, time of closest approach (TCA) and predicted **miss
distance**. A small miss distance IS "low transverse/sidereal motion"; a
target drifting across the sky has a large miss by construction. A track is
flagged when it closes ≥ 2 m/s, arrives within 60 s, and misses by ≤ 75 m
(`VR_CONFIG.THREAT`), smoothed by a per-track EMA with enter/exit hysteresis
so noisy velocity estimates don't flicker the warning.

Flagged tracks: designator flashes red/yellow, gets a pulsing ring, the
label switches to `!! #id <range> TCA <s>`, edge arrows give them top
priority, and the data panel shows `⚠ INTERCEPT COURSE — TCA / MISS` plus a
global `⚠ INTERCEPT ×n` counter. This deliberately runs client-side: only
the headset knows where the operator is (the server never sees GEO_POSE).

## Depth cues

Range on a designator dome is otherwise just a number, so three cues are
layered (`VR_CONFIG.DEPTH`):
1. **Size attenuation** — designator size scales as `(500 m / range)^0.35`,
   clamped ×0.65…×1.6, so nearer targets read bigger at a glance.
2. **Far fade** — beyond 2 km opacity falls off toward 0.5.
3. **True-depth placement** — targets closer than the 20 m dome radius are
   placed at their TRUE distance, so real binocular stereopsis and motion
   parallax take over exactly in the range band where human depth perception
   actually works.

## Controls (Steam Frame Controllers / xr-standard)

| | Right controller | Left controller (HUD mode) | Left controller (tabletop) |
|---|---|---|---|
| Trigger | select pointed track | toggle labels | toggle trails |
| Grip | — | — | hold to grab/drag table |
| A / X | HUD ⇄ TABLETOP | toggle compass/horizon | toggle rays |
| B / Y | align (HUD) / reset (tabletop) | toggle node markers | toggle voxels |
| Stick | rotate + zoom tabletop | — | pan tabletop |
| Stick click | center on selected (tabletop) | toggle data panel | toggle data panel |

Flat mode (no headset): mouse-drag orbit + wheel zoom; standard gamepad
(left stick orbit, right stick pan, triggers zoom, A cycle selection,
B deselect, X/Y/LB mode-aware layer toggles, RB mode, Start reset, Back
panel); keyboard `k/n/l` compass/nodes/labels, `r/v/t` tabletop layers,
`a` align, `m` mode, `Tab` cycle selection, `c` center, `h` panel,
`+/-` zoom, `Esc` deselect.

## URL parameters

| Param | Meaning |
|---|---|
| `?mock=true` | frontend-only simulated scene (no server, no phone) |
| `?ws=ws://host:5000/ws` | server WebSocket (default `localhost` — must be set on the headset) |
| `?geo=ws://host:8790` | GeoTether feed (default `192.168.42.129` = stock USB-tether gateway); `?geo=off` disables |
| `?lat=&lon=&alt=&heading=` | manual observer pose instead of the phone |
| `?mode=tabletop` | start in the CIC miniature instead of the HUD |
| `?scale=2000` | initial tabletop scale 1:2000 |
| `?cluster=<id>` | subscribe to a specific cluster room |
| `?xr=ar` / `?xr=vr` | force the session type; default tries passthrough AR first, falls back to VR (where a ground grid + horizon substitute for the real world) |
| `?panel=off` | start with the floating data panel hidden (toggle any time: L-stick-click / `h` / gamepad Back) |

## Running on the Steam Frame

The app is served as a static page (any HTTP server) on the LAN.
Delivery paths, in order of practicality today:

1. **PC-VR streaming (recommended):** run a WebXR-capable Chromium on the
   SteamVR PC (`--enable-features=WebXR` with the SteamVR OpenXR runtime) and
   stream to the Frame over Steam Link. Note passthrough is not available
   over streaming — HUD mode then renders on the virtual horizon/grid (VR).
2. **On-device browser:** SteamOS desktop mode can run Chromium (ARM Linux).
   When the on-device browser exposes WebXR with the `immersive-ar` blend
   mode, the same URL delivers true passthrough MR standalone.
3. **Flat fallback anywhere** for development — no headset required.

Tethering: when the phone USB-tethers the headset, the phone is the
headset's gateway (default `192.168.42.129`) and the headset reaches the
tracking server through the phone's WiFi — both WebSockets share the tether.
Alternatively keep the headset on the LAN WiFi and point `?geo=` at the
phone's WLAN address (shown in the GeoTether app).

A native OpenXR port would follow the same architecture (this codebase is
the reference for the overlay math and wire handling) but is out of scope —
nothing in this repo can build or test one.

## How this talks to the system (all connections)

| Link | Transport | Direction | Notes |
|---|---|---|---|
| headset ↔ tracking server | WS `:5000/ws` (JSON) | server→headset broadcast + `SUBSCRIBE_CLUSTER` commands | the only server connection; auto-subscribes the first cluster or `?cluster=` |
| phone → headset | WS `:8790` (GEO_POSE) | one-way | GeoTether app; never touches the server |
| phone → server (optional) | V3 UDP `:5005`, HMAC-signed | one-way | run the existing `code/android_node` app on the same phone and the operator doubles as a mobile SENSOR NODE |

**Can the headset itself detect?** Not from this WebXR app: browsers
deliberately do not expose the passthrough/tracking camera frames to WebXR
content, so on-headset detection needs a native OpenXR app. The practical
route today is the row above: `android_node` (CameraX + ML Kit → V3 UDP,
with its own GNSS/IMU pose) running on the tethered phone makes the
operator's position a detection node while GeoTether feeds the HUD — same
device, both roles.

## Development & verification (matches `ui-development` skill)

There is no package.json. Level 1 — syntax check any edited file:

```bash
cd VR-UI && npx esbuild --log-level=warning scene/hudOverlay.ts > /dev/null
```

Level 2 — browser preview: bundle app code, leave bare imports to the
importmap:

```bash
npx esbuild index.ts --bundle --format=esm --outfile=<PREVIEW>/dist/index.js \
  --external:three --external:zustand --external:zustand/vanilla
```

Copy `index.html` to `<PREVIEW>`, point the script tag at `./dist/index.js`,
serve, open `http://localhost:8123/?mock=true`. `window.__vrDebug` exposes
`{ store, sm }` for console probes (e.g. `sm.overlay` internals). In flat
mode the dome centers on a fixed virtual head at (0, 1.6, 0) so the orbit
camera can inspect the HUD from outside. `preview_screenshot` of this canvas
usually works (unlike deck.gl), but eval probes are more reliable.

## Contracts to keep

- `VR_CONFIG.COORDINATE_ORIGIN` must equal the server `reference.*` origin and
  NEW-UI-V2's `COORDINATE_ORIGIN` (geometry-conventions: one origin to rule
  them all).
- `types.ts` wire types mirror `NEW-UI-V2/types.ts` — change all together.
- `geo.ts` is a line-for-line port of `code/math_utils/geo.py` (validated
  against its round-trip example). ENU→scene mapping: `(E,N,U) → (E,U,−N)`,
  i.e. Y-up, North = −Z. Designator direction: `R_y(alignHeading) ·
  scene(track_ENU − observer_ENU)`.
- Store conventions inherited from NEW-UI-V2 (full-replace tracks, bounded
  trails, store-owned selection, reconnect discipline with buffered command
  queue) — see header comments in `store.ts` / `net/serverSocket.ts`.
- GEO_POSE wire format is defined by `types.ts::GeoPose` and produced by
  `vr_companion_android` — altitude is WGS84-ellipsoidal, heading is TRUE
  north (declination applied on the phone).

## File map

```
index.html            importmap (three, zustand) + DOM overlay shell
index.ts              bootstrap: params, store, sockets/mock, ENTER AR/VR
constants.ts          VR_CONFIG (origin, caps, HUD dome, colors) + Env URLs
types.ts              wire types (sync with NEW-UI-V2) + GeoPose + ViewMode
store.ts              zustand/vanilla state, bounded trails, selection
geo.ts                WGS84→ECEF→ENU port + ENU→scene mapping
net/serverSocket.ts   reconnecting server WS client (rooms, command queue)
net/geoSocket.ts      reconnecting GeoTether WS client (pose sanity checks)
threat.ts             headset-side CBDR intercept assessment (pure math)
scene/hudOverlay.ts   THE AR HUD: designator dome, threat cueing, depth
                      cues, edge arrows, compass
scene/sceneManager.ts renderer, AR/VR session, mode switching, render loop
scene/entities.ts     tabletop objects: tracks/rays/voxels/nodes/trails
input/controllers.ts  XR controllers + flat gamepad/mouse/keyboard
hud/hudPanel.ts       canvas-texture data panel (lazy-follow billboard)
mock.ts               ?mock=true scene (sensors, orbits, voxels, geo pose)
```
