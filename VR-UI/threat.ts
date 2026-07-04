/**
 * Intercept assessment — runs entirely on the headset (deliberately NOT on
 * the server: the server has no idea where the operator is; only this
 * client holds the GEO_POSE).
 *
 * Criterion: classic CBDR (constant bearing, decreasing range). For relative
 * position r = track − observer and relative velocity v:
 *   closing speed  = −(r·v)/|r|          (positive = range decreasing)
 *   TCA            = −(r·v)/|v|²         (time of closest approach)
 *   miss distance  = |r + v·TCA|         (how close it will actually get)
 * A small miss distance IS "not much sidereal/transverse motion" — a target
 * drifting sideways across the sky has a large miss by construction.
 * A track is an instant threat when it closes fast enough, arrives soon
 * enough, and misses by little enough (VR_CONFIG.THREAT). Consumers smooth
 * this with an EMA + hysteresis so noisy velocity estimates don't flicker
 * the warning.
 */

import { VR_CONFIG } from './constants';
import { GeoPose } from './types';

export interface ThreatAssessment {
    closingMs: number;   // + = range decreasing
    tcaS: number;        // time to closest approach; Infinity if opening
    missM: number;       // predicted miss distance at TCA; Infinity if opening
    instant: boolean;    // raw per-frame verdict (apply hysteresis before UI)
}

const MIN_REL_SPEED_SQ = 0.25;   // <0.5 m/s relative: kinematics meaningless

export function assessIntercept(
    rE: number, rN: number, rU: number,      // track − observer (ENU, m)
    vE: number, vN: number, vU: number,      // relative velocity (ENU, m/s)
): ThreatAssessment {
    const r2 = rE * rE + rN * rN + rU * rU;
    const r = Math.sqrt(r2);
    const v2 = vE * vE + vN * vN + vU * vU;
    const rv = rE * vE + rN * vN + rU * vU;

    const closingMs = r > 1e-6 ? -rv / r : 0;

    let tcaS = Infinity;
    let missM = Infinity;
    if (v2 > MIN_REL_SPEED_SQ) {
        const t = -rv / v2;
        if (t > 0) {
            tcaS = t;
            // |r + v·t|² expanded — avoids constructing the vector.
            missM = Math.sqrt(Math.max(0, r2 - (rv * rv) / v2));
        }
    }

    const T = VR_CONFIG.THREAT;
    const instant = closingMs >= T.MIN_CLOSING_MS
        && tcaS <= T.TCA_MAX_S
        && missM <= T.MISS_DISTANCE_M;

    return { closingMs, tcaS, missM, instant };
}

/**
 * Observer velocity in ENU from the geo pose. Approximation: uses the
 * compass heading as course-over-ground, gated to walking speeds and above —
 * a stationary operator (the normal case) contributes zero.
 */
export function observerVelocityEnu(pose: GeoPose | null): [number, number, number] {
    if (!pose || !isFinite(pose.speed_ms) || pose.speed_ms < 0.5
        || !isFinite(pose.heading_deg)) {
        return [0, 0, 0];
    }
    const h = pose.heading_deg * Math.PI / 180;
    return [Math.sin(h) * pose.speed_ms, Math.cos(h) * pose.speed_ms, 0];
}
