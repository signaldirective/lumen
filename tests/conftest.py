import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from lumen.settings import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "settings.json")
