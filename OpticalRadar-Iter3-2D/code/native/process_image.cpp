/*
 * process_image.cpp
 * PURPOSE: High-speed ray tracing for the voxel grid.
 * 
 * This C++ implementation provides 10-100x speedup over Python.
 * Uses pybind11 for Python bindings.
 */

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <cmath>
#include <algorithm>

namespace py = pybind11;


// Voxel grid ray marching
int add_ray_to_grid(
    py::array_t<float> grid,
    float origin_x, float origin_y, float origin_z,
    float dir_x, float dir_y, float dir_z,
    float intensity,
    float step_size,
    float max_distance,
    float resolution,
    float grid_origin_x, float grid_origin_y, float grid_origin_z
) {
    auto grid_buf = grid.mutable_unchecked<3>();
    
    int nx = grid_buf.shape(0);
    int ny = grid_buf.shape(1);
    int nz = grid_buf.shape(2);
    
    // Normalize direction
    float len = std::sqrt(dir_x * dir_x + dir_y * dir_y + dir_z * dir_z);
    if (len < 1e-10) return 0;
    
    dir_x /= len;
    dir_y /= len;
    dir_z /= len;
    
    int updated = 0;
    float t = 0.0f;
    
    while (t < max_distance) {
        // Current position
        float px = origin_x + t * dir_x;
        float py = origin_y + t * dir_y;
        float pz = origin_z + t * dir_z;
        
        // Convert to grid indices
        int ix = static_cast<int>((px - grid_origin_x) / resolution);
        int iy = static_cast<int>((py - grid_origin_y) / resolution);
        int iz = static_cast<int>((pz - grid_origin_z) / resolution);
        
        // Check bounds
        if (ix >= 0 && ix < nx && iy >= 0 && iy < ny && iz >= 0 && iz < nz) {
            grid_buf(ix, iy, iz) += intensity;
            updated++;
        }
        
        t += step_size;
    }
    
    return updated;
}


// Batch ray marching for multiple rays
int add_rays_batch(
    py::array_t<float> grid,
    py::array_t<float> origins,      // (N, 3)
    py::array_t<float> directions,   // (N, 3)
    py::array_t<float> intensities,  // (N,)
    float step_size,
    float max_distance,
    float resolution,
    float grid_origin_x, float grid_origin_y, float grid_origin_z
) {
    auto origins_buf = origins.unchecked<2>();
    auto dirs_buf = directions.unchecked<2>();
    auto intensities_buf = intensities.unchecked<1>();
    
    int n_rays = origins_buf.shape(0);
    int total_updated = 0;
    
    for (int i = 0; i < n_rays; i++) {
        total_updated += add_ray_to_grid(
            grid,
            origins_buf(i, 0), origins_buf(i, 1), origins_buf(i, 2),
            dirs_buf(i, 0), dirs_buf(i, 1), dirs_buf(i, 2),
            intensities_buf(i),
            step_size, max_distance, resolution,
            grid_origin_x, grid_origin_y, grid_origin_z
        );
    }
    
    return total_updated;
}


// Apply decay to entire grid
void decay_grid(py::array_t<float> grid, float decay_rate) {
    auto grid_buf = grid.mutable_unchecked<3>();
    
    int nx = grid_buf.shape(0);
    int ny = grid_buf.shape(1);
    int nz = grid_buf.shape(2);
    
    for (int x = 0; x < nx; x++) {
        for (int y = 0; y < ny; y++) {
            for (int z = 0; z < nz; z++) {
                grid_buf(x, y, z) *= decay_rate;
            }
        }
    }
}


// Find hot voxels above threshold
py::array_t<float> find_hot_voxels(
    py::array_t<float> grid,
    float threshold,
    float resolution,
    float grid_origin_x, float grid_origin_y, float grid_origin_z
) {
    auto grid_buf = grid.unchecked<3>();
    
    int nx = grid_buf.shape(0);
    int ny = grid_buf.shape(1);
    int nz = grid_buf.shape(2);
    
    // Count hot voxels first
    int count = 0;
    for (int x = 0; x < nx; x++) {
        for (int y = 0; y < ny; y++) {
            for (int z = 0; z < nz; z++) {
                if (grid_buf(x, y, z) >= threshold) {
                    count++;
                }
            }
        }
    }
    
    // Allocate result array (count, 4) - x, y, z, heat
    py::array_t<float> result({count, 4});
    auto result_buf = result.mutable_unchecked<2>();
    
    int idx = 0;
    for (int x = 0; x < nx; x++) {
        for (int y = 0; y < ny; y++) {
            for (int z = 0; z < nz; z++) {
                float heat = grid_buf(x, y, z);
                if (heat >= threshold) {
                    // Convert to world coordinates (voxel center)
                    result_buf(idx, 0) = grid_origin_x + (x + 0.5f) * resolution;
                    result_buf(idx, 1) = grid_origin_y + (y + 0.5f) * resolution;
                    result_buf(idx, 2) = grid_origin_z + (z + 0.5f) * resolution;
                    result_buf(idx, 3) = heat;
                    idx++;
                }
            }
        }
    }
    
    return result;
}


PYBIND11_MODULE(optical_radar_native, m) {
    m.doc() = "High-performance C++ extensions for OpticalRadar";
    
    m.def("add_ray_to_grid", &add_ray_to_grid,
          "Add heat along a ray through the voxel grid",
          py::arg("grid"),
          py::arg("origin_x"), py::arg("origin_y"), py::arg("origin_z"),
          py::arg("dir_x"), py::arg("dir_y"), py::arg("dir_z"),
          py::arg("intensity"),
          py::arg("step_size") = 0.5f,
          py::arg("max_distance") = 150.0f,
          py::arg("resolution") = 1.0f,
          py::arg("grid_origin_x") = 0.0f,
          py::arg("grid_origin_y") = 0.0f,
          py::arg("grid_origin_z") = 0.0f);
    
    m.def("add_rays_batch", &add_rays_batch,
          "Add multiple rays to the grid in batch",
          py::arg("grid"),
          py::arg("origins"),
          py::arg("directions"),
          py::arg("intensities"),
          py::arg("step_size") = 0.5f,
          py::arg("max_distance") = 150.0f,
          py::arg("resolution") = 1.0f,
          py::arg("grid_origin_x") = 0.0f,
          py::arg("grid_origin_y") = 0.0f,
          py::arg("grid_origin_z") = 0.0f);
    
    m.def("decay_grid", &decay_grid,
          "Apply decay to entire grid",
          py::arg("grid"),
          py::arg("decay_rate"));
    
    m.def("find_hot_voxels", &find_hot_voxels,
          "Find voxels above heat threshold",
          py::arg("grid"),
          py::arg("threshold"),
          py::arg("resolution") = 1.0f,
          py::arg("grid_origin_x") = 0.0f,
          py::arg("grid_origin_y") = 0.0f,
          py::arg("grid_origin_z") = 0.0f);
}
