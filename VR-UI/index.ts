/**
 * VR-UI bootstrap.
 *
 * URL parameters:
 *   ?mock=true            frontend-only simulated scene (no server, no phone)
 *   ?ws=ws://host:5000/ws server WebSocket (default: constants.Env.WS_URL)
 *   ?geo=ws://host:8790   GeoTether phone feed; ?geo=off disables it
 *   ?lat=&lon=&alt=&heading=   manual observer pose (implies geo off)
 *   ?mode=hud|tabletop    initial view mode (default hud; 'world' = hud alias)
 *   ?scale=1000           initial tabletop denominator (1:N)
 *   ?cluster=<id>         subscribe to a specific cluster room
 *   ?xr=ar|vr             force session type (default: AR/passthrough when
 *                         supported, else VR; legacy ?ar=true == ?xr=ar)
 */

import { VR_CONFIG, Env } from './constants';
import { createVRStore } from './store';
import { SceneManager, XRPreference } from './scene/sceneManager';
import { ServerSocket } from './net/serverSocket';
import { GeoSocket } from './net/geoSocket';
import { startMockData } from './mock';
import { ViewMode } from './types';

const params = new URLSearchParams(window.location.search);
const mock = params.get('mock') === 'true';
const wsUrl = params.get('ws') || Env.WS_URL;
const geoParam = params.get('geo');
const manualLat = params.get('lat');
const manualLon = params.get('lon');

const xrParam = params.get('xr');
const xrPref: XRPreference = xrParam === 'vr' ? 'vr'
    : (xrParam === 'ar' || params.get('ar') === 'true') ? 'ar' : 'auto';

const initialMode: ViewMode = params.get('mode') === 'tabletop' ? 'TABLETOP' : 'HUD';
const scaleDenom = Number(params.get('scale'));
const store = createVRStore({
    viewMode: initialMode,
    tabletopScale: scaleDenom > 0 ? 1 / scaleDenom : undefined,
    activeClusterId: params.get('cluster'),
    mockMode: mock,
    // Data panel starts hidden with ?panel=off; toggle any time with
    // L-stick-click / `h` / gamepad Back.
    hudVisible: params.get('panel') === 'off' ? false : undefined,
});

const sm = new SceneManager(store, xrPref);

// ---------------------------------------------------------------------------
// Data sources
// ---------------------------------------------------------------------------
let serverSocket: ServerSocket | null = null;
let stopMock: (() => void) | null = null;

if (mock) {
    stopMock = startMockData(store);
} else {
    serverSocket = new ServerSocket(wsUrl, store);
    serverSocket.connect();

    if (manualLat != null && manualLon != null) {
        // Manual observer pose (no phone): static fix, optional fixed heading.
        store.getState().setGeoPose({
            lat: Number(manualLat),
            lon: Number(manualLon),
            alt: Number(params.get('alt') ?? VR_CONFIG.COORDINATE_ORIGIN.alt),
            accuracy_m: 0,
            heading_deg: Number(params.get('heading') ?? NaN),
            heading_accuracy_deg: 0,
            speed_ms: 0,
            timestamp: Date.now() / 1000,
            provider: 'manual',
        });
        const h = Number(params.get('heading'));
        if (isFinite(h)) store.getState().setAlignmentHeading(h);
    } else if (geoParam !== 'off') {
        new GeoSocket(geoParam || Env.GEO_WS_URL, store).connect();
    }
}

// ---------------------------------------------------------------------------
// DOM overlay (flat mode / pre-session): status strip + ENTER VR button
// ---------------------------------------------------------------------------
const overlay = document.getElementById('overlay')!;
const statusEl = document.getElementById('status')!;
const enterBtn = document.getElementById('enter-vr') as HTMLButtonElement;
const modeLink = document.getElementById('mode-link') as HTMLAnchorElement;

if (mock) {
    modeLink.textContent = 'GO LIVE';
    modeLink.href = window.location.pathname;
} else {
    modeLink.textContent = 'RUN SIM MODE';
    modeLink.href = '?mock=true';
}

const xr = (navigator as any).xr;
if (xr && typeof xr.isSessionSupported === 'function') {
    // Prefer passthrough AR (the point of HUD mode); fall back to VR.
    (async () => {
        const arOk = xrPref !== 'vr'
            && await xr.isSessionSupported('immersive-ar').catch(() => false);
        const vrOk = xrPref !== 'ar'
            && await xr.isSessionSupported('immersive-vr').catch(() => false);
        if (arOk) {
            enterBtn.disabled = false;
            enterBtn.textContent = 'ENTER AR';
        } else if (vrOk) {
            enterBtn.disabled = false;
            enterBtn.textContent = 'ENTER VR';
        } else {
            enterBtn.textContent = 'NO HMD — FLAT MODE';
        }
    })();
} else {
    enterBtn.textContent = 'WEBXR UNAVAILABLE — FLAT MODE';
}

enterBtn.addEventListener('click', () => {
    sm.startXR().catch((err: Error) => {
        console.error('[VR] Failed to start XR session:', err);
        statusEl.textContent = `XR session failed: ${err.message}`;
    });
});

sm.renderer.xr.addEventListener('sessionstart', () => { overlay.style.display = 'none'; });
sm.renderer.xr.addEventListener('sessionend', () => { overlay.style.display = 'block'; });

// Status strip: 2 Hz summary of the store (flat-mode counterpart of the HUD).
setInterval(() => {
    const s = store.getState();
    const srv = mock ? 'SIM' : (s.serverConnected ? 'LIVE'
        : (s.serverReconnectAttempt > 0 ? `RECONNECTING (${s.serverReconnectAttempt})` : 'OFFLINE'));
    const geoAge = s.geoPose ? Date.now() / 1000 - s.geoPose.timestamp : Infinity;
    const geo = s.geoPose?.provider === 'manual' ? 'MANUAL'
        : (s.geoConnected && geoAge < VR_CONFIG.GEO_STALE_SECONDS ? 'OK'
            : (s.geoPose ? 'STALE' : '—'));
    const mode = s.viewMode === 'TABLETOP'
        ? `TABLETOP 1:${Math.round(1 / s.tabletopScale)}`
        : `AR HUD${s.alignmentHeadingDeg != null ? '' : ' (unaligned)'}`;
    statusEl.textContent =
        `${srv} | GEO ${geo} | ${mode} | TRK ${Object.keys(s.tracks).length}` +
        ` VOX ${s.voxels.length} RAY ${s.rays.length}` +
        (s.selectedTrackId != null ? ` | SEL #${s.selectedTrackId}` : '');
}, 500);

// Expose for debugging / browser-preview verification (mirrors the
// ui-development preview workflow, which probes app state via console eval).
// stopMock lets a probe freeze the sim and inject synthetic store state.
(window as any).__vrDebug = { store, sm, stopMock };

console.log('[VR] OpticalRadar VR-UI started', { mock, xrPref, wsUrl, mode: initialMode });
