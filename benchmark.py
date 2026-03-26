import timeit
import numpy as np

# Original implementation of greedy_assignment
def greedy_assignment_original(
    cost_matrix: np.ndarray,
    max_distance: float = 50.0
):
    n_tracks, n_dets = cost_matrix.shape

    if n_tracks == 0:
        return [], [], list(range(n_dets))
    if n_dets == 0:
        return [], list(range(n_tracks)), []

    matches = []
    used_tracks = set()
    used_dets = set()

    # Get all valid (track, det, cost) tuples
    candidates = []
    for i in range(n_tracks):
        for j in range(n_dets):
            if cost_matrix[i, j] <= max_distance:
                candidates.append((cost_matrix[i, j], i, j))

    # Sort by cost (ascending)
    candidates.sort()

    # Greedily assign
    for cost, track_idx, det_idx in candidates:
        if track_idx not in used_tracks and det_idx not in used_dets:
            matches.append((track_idx, det_idx))
            used_tracks.add(track_idx)
            used_dets.add(det_idx)

    unmatched_tracks = [i for i in range(n_tracks) if i not in used_tracks]
    unmatched_dets = [j for j in range(n_dets) if j not in used_dets]

    return matches, unmatched_tracks, unmatched_dets

def greedy_assignment_optimized3(
    cost_matrix: np.ndarray,
    max_distance: float = 50.0
):
    n_tracks, n_dets = cost_matrix.shape

    if n_tracks == 0:
        return [], [], list(range(n_dets))
    if n_dets == 0:
        return [], list(range(n_tracks)), []

    matches = []
    used_tracks = set()
    used_dets = set()

    # Get all valid (track, det, cost) tuples using NumPy vectorization
    valid_indices = np.where(cost_matrix <= max_distance)

    # Convert arrays to lists for faster iteration in Python
    # This combines the extraction and tuple creation
    candidates = list(zip(
        cost_matrix[valid_indices].tolist(),
        valid_indices[0].tolist(),
        valid_indices[1].tolist()
    ))

    # Sort by cost (ascending)
    candidates.sort()

    # Greedily assign
    for cost, track_idx, det_idx in candidates:
        if track_idx not in used_tracks and det_idx not in used_dets:
            matches.append((track_idx, det_idx))
            used_tracks.add(track_idx)
            used_dets.add(det_idx)

    unmatched_tracks = [i for i in range(n_tracks) if i not in used_tracks]
    unmatched_dets = [j for j in range(n_dets) if j not in used_dets]

    return matches, unmatched_tracks, unmatched_dets

def setup(n_tracks, n_dets):
    np.random.seed(42)
    cost_matrix = np.random.uniform(0, 100, size=(n_tracks, n_dets))
    return cost_matrix

def run_benchmark():
    n_tracks = 500
    n_dets = 500
    print(f"Benchmarking greedy_assignment with {n_tracks}x{n_dets} matrix")
    cost_matrix = setup(n_tracks, n_dets)

    # Verify correctness
    orig_res = greedy_assignment_original(cost_matrix, 20.0)
    opt_res = greedy_assignment_optimized3(cost_matrix, 20.0)

    assert orig_res[0] == opt_res[0], "Matches differ!"
    assert orig_res[1] == opt_res[1], "Unmatched tracks differ!"
    assert orig_res[2] == opt_res[2], "Unmatched dets differ!"
    print("Correctness verified: results are identical.")

    num_runs = 50
    orig_time = timeit.timeit(lambda: greedy_assignment_original(cost_matrix, 20.0), number=num_runs)
    opt_time = timeit.timeit(lambda: greedy_assignment_optimized3(cost_matrix, 20.0), number=num_runs)

    print(f"\nOriginal time ({num_runs} runs): {orig_time:.4f} seconds ({orig_time/num_runs:.5f} sec/run)")
    print(f"Optimized time ({num_runs} runs): {opt_time:.4f} seconds ({opt_time/num_runs:.5f} sec/run)")
    print(f"Speedup: {orig_time / opt_time:.2f}x")

if __name__ == '__main__':
    run_benchmark()
