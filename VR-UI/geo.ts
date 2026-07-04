/**
 * WGS84 → ENU conversion, ported verbatim from code/math_utils/geo.py so the
 * headset agrees with the server about where things are. See the
 * geometry-conventions skill; verified against the Python round-trip example
 * there (37.7758,-122.4180,25 rel 37.7749,-122.4194,0 → E=123.339 N=99.894
 * U=24.998).
 *
 * Also owns the ENU → three.js scene mapping: three/WebXR is right-handed
 * Y-up with -Z forward, so (E, N, U) → (x=E, y=U, z=-N). With an unrotated
 * world group, -Z (the user's initial facing) is North.
 */

import { Vector3 } from './types';

// WGS84 ellipsoid parameters (identical to math_utils/geo.py)
export const WGS84_A = 6378137.0;
export const WGS84_B = 6356752.314245;
export const WGS84_E2 = 1.0 - (WGS84_B * WGS84_B) / (WGS84_A * WGS84_A);

const DEG = Math.PI / 180.0;

export function wgs84ToEcef(lat: number, lon: number, alt: number): Vector3 {
    const latRad = lat * DEG;
    const lonRad = lon * DEG;

    const sinLat = Math.sin(latRad);
    const cosLat = Math.cos(latRad);
    const sinLon = Math.sin(lonRad);
    const cosLon = Math.cos(lonRad);

    // Radius of curvature in the prime vertical
    const N = WGS84_A / Math.sqrt(1.0 - WGS84_E2 * sinLat * sinLat);

    const X = (N + alt) * cosLat * cosLon;
    const Y = (N + alt) * cosLat * sinLon;
    const Z = (N * (1.0 - WGS84_E2) + alt) * sinLat;

    return [X, Y, Z];
}

export function ecefToEnu(
    x: number, y: number, z: number,
    refLat: number, refLon: number, refAlt: number
): Vector3 {
    const [refX, refY, refZ] = wgs84ToEcef(refLat, refLon, refAlt);

    const dx = x - refX;
    const dy = y - refY;
    const dz = z - refZ;

    const latRad = refLat * DEG;
    const lonRad = refLon * DEG;

    const sinLat = Math.sin(latRad);
    const cosLat = Math.cos(latRad);
    const sinLon = Math.sin(lonRad);
    const cosLon = Math.cos(lonRad);

    const E = -sinLon * dx + cosLon * dy;
    const N = -sinLat * cosLon * dx - sinLat * sinLon * dy + cosLat * dz;
    const U = cosLat * cosLon * dx + cosLat * sinLon * dy + sinLat * dz;

    return [E, N, U];
}

export function wgs84ToEnu(
    lat: number, lon: number, alt: number,
    refLat: number, refLon: number, refAlt: number
): Vector3 {
    const [x, y, z] = wgs84ToEcef(lat, lon, alt);
    return ecefToEnu(x, y, z, refLat, refLon, refAlt);
}

// ---------------------------------------------------------------------------
// ENU ↔ three.js scene frame
// ---------------------------------------------------------------------------

/** ENU metres → scene-local coordinates (Y-up, North = -Z). */
export function enuToSceneXYZ(e: number, n: number, u: number): [number, number, number] {
    return [e, u, -n];
}

export function enuVecToSceneXYZ(v: Vector3): [number, number, number] {
    return [v[0], v[2], -v[1]];
}

/** Azimuth/elevation (deg, az 0=N CW, el 0=horizon up+) → unit ENU direction. */
export function anglesToEnuDirection(azimuthDeg: number, elevationDeg: number): Vector3 {
    const az = azimuthDeg * DEG;
    const el = elevationDeg * DEG;
    const cosEl = Math.cos(el);
    return [Math.sin(az) * cosEl, Math.cos(az) * cosEl, Math.sin(el)];
}
