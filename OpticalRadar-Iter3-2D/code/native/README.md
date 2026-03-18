# Native Acceleration Module

This directory contains an optional C++ acceleration module for performance-critical voxel grid operations.

## Overview

The `optical_radar_native` module provides C++ implementations of:
- Ray tracing through the voxel grid (`add_ray_to_grid`)
- Batch ray processing (`add_rays_batch`)
- Grid decay operations (`decay_grid`)
- Hot voxel detection (`find_hot_voxels`)

**Note:** The Python fallback in `voxel_grid.py` provides identical functionality. The native module is purely an optimization.

## Building the Native Module

### Prerequisites

1. **Python development headers**
   ```bash
   # Ubuntu/Debian
   sudo apt-get install python3-dev
   
   # Windows: Included with Python installation
   ```

2. **C++ compiler**
   ```bash
   # Ubuntu/Debian
   sudo apt-get install g++
   
   # Windows: Install Visual Studio Build Tools
   ```

3. **pybind11**
   ```bash
   pip install pybind11
   ```

### Build Steps

From this directory (`code/native/`):

```bash
# Standard build
python setup.py build_ext --inplace

# Or install to site-packages
pip install .
```

### Verification

```python
from native import is_native_available, NATIVE_AVAILABLE

print(f"Native acceleration: {'enabled' if NATIVE_AVAILABLE else 'disabled'}")
```

## Fallback Behavior

If the native module fails to build or import:
- The system automatically uses pure Python implementations
- No functionality is lost, only performance
- A warning is logged at startup

## Performance Comparison

| Operation | Python | Native | Speedup |
|-----------|--------|--------|---------|
| add_ray (single) | ~1.5ms | ~0.1ms | ~15x |
| add_rays_batch (100) | ~150ms | ~3ms | ~50x |
| decay_grid | ~50ms | ~2ms | ~25x |
| find_hot_voxels | ~30ms | ~1ms | ~30x |

*Benchmarks on Intel i7-10750H with 200x200x100 grid at 1m resolution*

## Troubleshooting

### Module not found
```
ImportError: No module named 'optical_radar_native'
```
**Solution:** Build the module with `python setup.py build_ext --inplace`

### Compiler errors on Windows
```
error: Microsoft Visual C++ 14.0 or greater is required
```
**Solution:** Install [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)

### pybind11 not found
```
ModuleNotFoundError: No module named 'pybind11'
```
**Solution:** `pip install pybind11`
