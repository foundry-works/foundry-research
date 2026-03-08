"""Pytest conftest — adds scripts/ to sys.path for all tests."""

import os
import sys

_HERE = os.path.dirname(__file__)

# Add tests/ and scripts/ to sys.path once for all tests
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, os.pardir, "skills", "deep-research", "scripts"))
