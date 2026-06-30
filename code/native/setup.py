
"""
Native module setup.py
PURPOSE: Build configuration for C++ extension.
"""

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
import sys
import os


class get_pybind_include:
    """Helper class to determine pybind11 include path."""
    def __init__(self, user=False):
        self.user = user

    def __str__(self):
        import pybind11
        return pybind11.get_include(self.user)


ext_modules = [
    Extension(
        'optical_radar_native',
        sources=['process_image.cpp'],
        include_dirs=[
            get_pybind_include(),
            get_pybind_include(user=True),
        ],
        language='c++',
        extra_compile_args=['-std=c++14', '-O3', '-ffast-math'],
    ),
]


setup(
    name='optical_radar_native',
    version='0.1.0',
    author='OpticalRadar Team',
    description='High-performance C++ extensions for OpticalRadar',
    ext_modules=ext_modules,
    cmdclass={'build_ext': build_ext},
    python_requires='>=3.8',
    install_requires=['pybind11>=2.6.0'],
)
