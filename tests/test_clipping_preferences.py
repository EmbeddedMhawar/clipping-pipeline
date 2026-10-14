#!/usr/bin/env python3
"""
tests/test_clipping_preferences.py

Unit tests for scripts/clipping_preferences.py (Preference Codification Engine).
"""

import os
import sys
import unittest
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.clipping_preferences import TestClippingPreferences

if __name__ == "__main__":
    unittest.main()
