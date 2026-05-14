import sys
import os
import time
import numpy as np
from server.voxel_grid import HotVoxel, VoxelGridConfig
from scipy.spatial import cKDTree

# Import original logic to compare against
def cluster_hot_voxels_original(hot_voxels, cluster_radius=3.0):
    if not hot_voxels:
        return []

    clusters = []
    used = [False] * len(hot_voxels)

    for i, voxel in enumerate(hot_voxels):
        if used[i]:
            continue

        cluster_positions = [voxel.center]
        cluster_weights = [voxel.heat]
        used[i] = True

        for j, other in enumerate(hot_voxels[i+1:], i+1):
            if used[j]:
                continue

            dist = np.linalg.norm(voxel.center - other.center)
            if dist <= cluster_radius:
                cluster_positions.append(other.center)
                cluster_weights.append(other.heat)
                used[j] = True

        weights = np.array(cluster_weights)
        positions = np.array(cluster_positions)
        centroid = np.average(positions, axis=0, weights=weights)
        clusters.append(centroid)

    return clusters

# Import KDTree logic directly from module
from server.voxel_grid import VoxelGrid

def main():
    np.random.seed(42)
    num_voxels = 10000
    hot_voxels = []

    # Create random hot voxels clustered in a few spots
    centers = [np.array([10.0, 10.0, 5.0]), np.array([-20.0, 30.0, 2.0]), np.array([50.0, -10.0, 10.0])]
    for _ in range(num_voxels):
        c = centers[np.random.randint(0, len(centers))]
        pos = c + np.random.randn(3) * 5.0
        v = HotVoxel(x=0, y=0, z=0, heat=10.0, center=pos)
        hot_voxels.append(v)

    print(f"Benchmarking with {num_voxels} hot voxels...")

    start_time = time.time()
    clusters_orig = cluster_hot_voxels_original(hot_voxels, cluster_radius=3.0)
    end_time = time.time()
    time_orig = end_time - start_time
    print(f"Original O(N^2) Implementation: {time_orig:.4f} seconds")

    vg = VoxelGrid(VoxelGridConfig())
    start_time = time.time()
    clusters_kd = vg.cluster_hot_voxels(hot_voxels, cluster_radius=3.0)
    end_time = time.time()
    time_kd = end_time - start_time
    print(f"KDTree O(N log N) Implementation: {time_kd:.4f} seconds")

    print(f"\nSpeedup: {time_orig / time_kd:.2f}x")

if __name__ == "__main__":
    main()
