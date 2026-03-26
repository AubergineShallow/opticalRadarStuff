import time
import numpy as np
import sys
import os

# Create mock native module
class MockNativeWrapper:
    @staticmethod
    def add_ray_to_grid(*args):
        time.sleep(0.001)
        return 100

    @staticmethod
    def add_rays_batch(*args):
        time.sleep(0.0015)
        return 1000

sys.modules['native'] = type('MockModule', (), {'native_wrapper': MockNativeWrapper()})
sys.modules['native.native_wrapper'] = MockNativeWrapper()

from voxel_grid import VoxelGrid, VoxelGridConfig

class MockRay:
    def __init__(self, origin, direction, intensity):
        self.origin = origin
        self.direction = direction
        self.intensity = intensity

def run_benchmark():
    config = VoxelGridConfig(width_m=200, height_m=100, depth_m=200, resolution_m=1.0)
    grid = VoxelGrid(config)

    # Generate mock rays
    num_rays = 1000
    rays = []
    for _ in range(num_rays):
        origin = np.random.uniform(-50, 50, 3)
        direction = np.random.uniform(-1, 1, 3)
        direction /= np.linalg.norm(direction)
        rays.append(MockRay(origin, direction, 1.0))

    print(f"Benchmarking with {num_rays} rays (with native module mock)...")

    # Loop approach
    start_time = time.time()
    for ray in rays:
        grid.add_ray(ray.origin, ray.direction, ray.intensity)
    loop_time = time.time() - start_time
    print(f"Loop over add_ray: {loop_time:.4f} seconds")

    # Batch approach
    start_time = time.time()
    grid.add_rays_batch(rays)
    batch_time = time.time() - start_time
    print(f"add_rays_batch: {batch_time:.4f} seconds")

    if batch_time < loop_time:
        improvement = (loop_time - batch_time) / loop_time * 100
        print(f"Speedup: {improvement:.2f}%")
    else:
        print("Batch was not faster than loop.")

if __name__ == '__main__':
    run_benchmark()
