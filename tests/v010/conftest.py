"""Real-engine CI must fail when its configured tools are missing."""
import os
import shutil

import pytest


def pytest_collection_finish(session):
    if os.environ.get("TOPOS_REQUIRE_REAL_ENGINES") != "1":
        return
    missing = [name for name in ("xtb", "crest")
               if shutil.which(os.environ.get(f"TOPOS_{name.upper()}_EXECUTABLE", name)) is None]
    if missing:
        raise pytest.UsageError("Required genuine engines missing: " + ", ".join(missing))
