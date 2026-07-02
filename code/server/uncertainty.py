

"""
uncertainty.py
PURPOSE: Turn per-node angular (bearing) uncertainty into a 3D positional
measurement covariance for the tracker.

A passive optical node measures a *bearing* (azimuth/elevation), not a range.
Its bearing precision sigma_theta comes from the node's optics -- field of view
over sensor resolution (see common.node_specs). At range rho from a node, that
bearing error maps to a cross-range positional error of ~rho*sigma_theta, while
the along-ray (depth) direction is almost unconstrained by that one node.

When several nodes see the same target from different directions, their thin,
depth-uncertain error ellipsoids intersect into a compact region -- which is
exactly what triangulation does. We fuse them in information (inverse-covariance)
form:

    J = sum_c [ (1/sigma_range^2) * d_c d_c^T
                + (1/s_c^2) * (I - d_c d_c^T) ]
    R = inv(J)

where, for node c: d_c is the unit vector from the node to the target,
s_c = rho_c * sigma_theta_c is its cross-range std-dev, and sigma_range is a
large along-ray std-dev (a single bearing barely constrains depth). One node
yields a long, thin, depth-uncertain R; two well-separated nodes yield a small,
near-isotropic R. Distant nodes self-attenuate (large s_c -> little information),
so no hard visibility gate is required. R is handed to the Kalman filter as the
per-measurement noise, so each fused detection is weighted by how well the nodes
that produced it actually pin it down.
"""

import numpy as np
from typing import Iterable, Optional, Tuple


def measurement_covariance(
    position,
    cameras: Iterable[Tuple[object, float]],
    sigma_range: float = 100.0,
    min_cross_range: float = 0.5,
    max_range: float = 500.0,
) -> Optional[np.ndarray]:
    """Fuse per-node bearing uncertainties into a 3x3 positional covariance.

    Args:
        position: detection position [x, y, z] in the same frame as the nodes.
        cameras: iterable of (origin[3], sigma_theta_rad) for the nodes that
            could see this detection.
        sigma_range: along-ray (depth) std-dev in metres for a single node.
        min_cross_range: floor on cross-range std-dev in metres (voxel-scale
            quantisation guard, keeps information finite for very near nodes).
        max_range: ignore nodes farther than this (metres).

    Returns:
        3x3 covariance matrix, or None if no usable node contributed (caller
        should then fall back to its default isotropic R).
    """
    position = np.asarray(position, dtype=float).reshape(3)
    J = np.zeros((3, 3))
    inv_sr2 = 1.0 / (sigma_range ** 2)
    used = 0

    for origin, sigma_theta in cameras:
        o = np.asarray(origin, dtype=float).reshape(3)
        v = position - o
        rho = float(np.linalg.norm(v))
        if rho <= 1e-6 or rho > max_range:
            continue
        d = v / rho
        s = max(rho * float(sigma_theta), min_cross_range)
        inv_s2 = 1.0 / (s * s)
        ddt = np.outer(d, d)
        J += inv_sr2 * ddt + inv_s2 * (np.eye(3) - ddt)
        used += 1

    if used == 0:
        return None

    # Small regularisation guards a degenerate (rank-deficient) J when every
    # contributing node is collinear with the target.
    J += np.eye(3) * (inv_sr2 * 1e-3)
    try:
        return np.linalg.inv(J)
    except np.linalg.LinAlgError:
        return None
