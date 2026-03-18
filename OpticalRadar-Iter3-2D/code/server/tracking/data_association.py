"""
data_association.py
PURPOSE: Match detections to existing tracks using Hungarian algorithm (2D fork).
"""

import numpy as np
from typing import List, Tuple, Optional
from scipy.optimize import linear_sum_assignment


def compute_cost_matrix(
    predicted_positions: List[np.ndarray],
    measurements: List[np.ndarray],
    max_distance: float = 50.0
) -> np.ndarray:
    """
    Compute cost matrix for detection-to-track assignment.

    Args:
        predicted_positions: List of predicted track positions (N x 2)
        measurements: List of detection positions (M x 2)
        max_distance: Maximum allowed distance for association

    Returns:
        Cost matrix (N x M) with Euclidean distances
    """
    n_tracks = len(predicted_positions)
    n_dets = len(measurements)

    if n_tracks == 0 or n_dets == 0:
        return np.zeros((n_tracks, n_dets))

    cost = np.full((n_tracks, n_dets), max_distance * 10, dtype=np.float64)

    for i, track_pos in enumerate(predicted_positions):
        for j, det_pos in enumerate(measurements):
            dist = np.linalg.norm(track_pos[:2] - det_pos[:2])
            if dist <= max_distance:
                cost[i, j] = dist

    return cost


def hungarian_assignment(
    cost_matrix: np.ndarray,
    max_distance: float = 50.0
) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
    """
    Solve assignment problem using Hungarian algorithm.

    Args:
        cost_matrix: Cost matrix (N_tracks x M_detections)
        max_distance: Maximum allowed distance for valid assignment

    Returns:
        Tuple of:
            - matches: List of (track_idx, detection_idx) pairs
            - unmatched_tracks: List of unmatched track indices
            - unmatched_detections: List of unmatched detection indices
    """
    n_tracks, n_dets = cost_matrix.shape

    if n_tracks == 0:
        return [], [], list(range(n_dets))
    if n_dets == 0:
        return [], list(range(n_tracks)), []

    track_indices, det_indices = linear_sum_assignment(cost_matrix)

    matches = []
    unmatched_tracks = set(range(n_tracks))
    unmatched_detections = set(range(n_dets))

    for track_idx, det_idx in zip(track_indices, det_indices):
        cost = cost_matrix[track_idx, det_idx]

        if cost <= max_distance:
            matches.append((track_idx, det_idx))
            unmatched_tracks.discard(track_idx)
            unmatched_detections.discard(det_idx)

    return matches, list(unmatched_tracks), list(unmatched_detections)


def greedy_assignment(
    cost_matrix: np.ndarray,
    max_distance: float = 50.0
) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
    """
    Greedy assignment (faster but suboptimal).

    Args:
        cost_matrix: Cost matrix (N_tracks x M_detections)
        max_distance: Maximum allowed distance

    Returns:
        Same format as hungarian_assignment
    """
    n_tracks, n_dets = cost_matrix.shape

    if n_tracks == 0:
        return [], [], list(range(n_dets))
    if n_dets == 0:
        return [], list(range(n_tracks)), []

    matches = []
    used_tracks = set()
    used_dets = set()

    candidates = []
    for i in range(n_tracks):
        for j in range(n_dets):
            if cost_matrix[i, j] <= max_distance:
                candidates.append((cost_matrix[i, j], i, j))

    candidates.sort()

    for cost, track_idx, det_idx in candidates:
        if track_idx not in used_tracks and det_idx not in used_dets:
            matches.append((track_idx, det_idx))
            used_tracks.add(track_idx)
            used_dets.add(det_idx)

    unmatched_tracks = [i for i in range(n_tracks) if i not in used_tracks]
    unmatched_dets = [j for j in range(n_dets) if j not in used_dets]

    return matches, unmatched_tracks, unmatched_dets


def associate(
    predicted_positions: List[np.ndarray],
    measurements: List[np.ndarray],
    max_distance: float = 50.0,
    use_hungarian: bool = True
) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
    """
    Associate detections to tracks.

    Args:
        predicted_positions: List of predicted track positions
        measurements: List of detection positions
        max_distance: Maximum association distance
        use_hungarian: Use Hungarian (True) or greedy (False)

    Returns:
        Tuple of (matches, unmatched_tracks, unmatched_detections)
    """
    cost_matrix = compute_cost_matrix(
        predicted_positions,
        measurements,
        max_distance
    )

    if use_hungarian:
        return hungarian_assignment(cost_matrix, max_distance)
    else:
        return greedy_assignment(cost_matrix, max_distance)


def iou_2d(
    box1: Tuple[np.ndarray, np.ndarray],
    box2: Tuple[np.ndarray, np.ndarray]
) -> float:
    """
    Calculate 2D IoU between two axis-aligned bounding boxes.

    Args:
        box1: Tuple of (min_corner, max_corner)  — 2D
        box2: Tuple of (min_corner, max_corner)  — 2D

    Returns:
        IoU value [0, 1]
    """
    min1, max1 = box1
    min2, max2 = box2

    inter_min = np.maximum(min1[:2], min2[:2])
    inter_max = np.minimum(max1[:2], max2[:2])

    inter_size = np.maximum(0, inter_max - inter_min)
    inter_area = np.prod(inter_size)

    if inter_area == 0:
        return 0.0

    size1 = max1[:2] - min1[:2]
    size2 = max2[:2] - min2[:2]
    area1 = np.prod(size1)
    area2 = np.prod(size2)

    union_area = area1 + area2 - inter_area

    return float(inter_area / union_area) if union_area > 0 else 0.0
