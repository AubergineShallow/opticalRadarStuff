"""Simulation module - virtual cameras and targets for testing."""

from .sim_utils import (
    degrees_to_radians, radians_to_degrees, enu_to_azel,
    generate_circular_positions, generate_figure_eight,
    add_noise, add_position_noise
)
from .sim_node import SimNode, SimTarget, SimCameraConfig, create_demo_simulation

__all__ = [
    'degrees_to_radians', 'radians_to_degrees', 'enu_to_azel',
    'generate_circular_positions', 'generate_figure_eight',
    'add_noise', 'add_position_noise',
    'SimNode', 'SimTarget', 'SimCameraConfig', 'create_demo_simulation',
]
