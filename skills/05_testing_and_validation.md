# Testing and Validation

## General Guidelines

- Internal test cases for math functionality shouldn't be executed as standalone scripts inside module directories; instead, they are designed as internal check functions that the custom test runner `code/system_test.py` calls.
- `code/system_test.py` checks known cases: For example, `wgs84_to_ecef` is tested for specific locations (Equator, Poles) and verified for round-trip consistency with `ecef_to_wgs84` at an acceptable tolerance (1e-7 degrees for angles, 1e-3 for meters).
- Python scripts that import from `code/` must ensure that the directory is correctly in the `PYTHONPATH` (`export PYTHONPATH=$PYTHONPATH:$(pwd)/code`).

## Dependency Management for Tests

Running `code/system_test.py` in environments where standard external packages (`numpy`, `scipy`, `opencv-python`, `pyyaml`, `websockets`) are unavailable requires strict dependency management.

- **Mocking Strategy:** `sys.modules` must be strategically mocked in a wrapper execution script.
- **Mocking NumPy:** When unit testing matrix and arithmetic logic with mocked NumPy, use a subclass of `list` to replicate basic `ndarray` behavior. This class must implement multidimensional indexing (`array[i, j, k]`), fundamental arithmetic operators (`__sub__`, `__mul__`, `__add__`, `__truediv__`), reverse arithmetic operators (`__rmul__`), and aggregations (`.sum()`, `.mean()`, `.max()`).
- **Avoiding Unnecessary Loads:** Ensure pure math modules (`code/math_utils/quaternion.py` and `code/math_utils/geo.py`) remain completely independent of libraries like `numpy`. Unused `numpy` imports in these modules must be removed or mocked if present.
- **Fail-Open Security Bypass:** For tests executed without valid security keys, the environment variable `OR_SECURITY_ENABLED='false'` must be injected to prevent fail-closed initialization errors in the server stack.
- **Lazy OpenCV Loading:** In `code/rpi/vision.py`, `cv2` is loaded lazily and assigned to `self._cv2` within the `VisionSystem` constructor. This strategy guarantees that the rest of the RPi logic is importable and testable in restricted CI environments lacking the OpenCV package.

## Pull Request Conventions

To maintain a clean and descriptive history, pull requests proposing testing improvements must strictly adhere to the following template:

- **Title Format:** `🧪 [testing improvement description]`
- **Body Requirements:** Must contain the following headers:
  - `🎯 What:` Explain what the test changes.
  - `📊 Coverage:` Specify the components or logic covered.
  - `✨ Result:` Summarize the outcome or status.