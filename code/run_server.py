#!/usr/bin/env python
"""
run_server.py - Launcher script for OpticalRadar server.

This script allows running the server directly without needing
to use `python -m server.server_main`.
"""

import sys
import os

# Add code directory to path
code_dir = os.path.dirname(os.path.abspath(__file__))
if code_dir not in sys.path:
    sys.path.insert(0, code_dir)

from server.server_main import main

if __name__ == "__main__":
    main()
