#!/usr/bin/env python3
"""Backward-compatible wrapper for `pixelcrew init`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pixelcrew.cli import main

main(["init", *sys.argv[1:]])
