from __future__ import annotations

import pytest

from backend.tests.golden_s1.golden_s1_runner import default_paths


@pytest.fixture(scope="session")
def golden_paths():
    return default_paths()
