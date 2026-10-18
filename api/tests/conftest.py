import os
from datetime import UTC, datetime

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.pop("AUTH_MODE", None)
os.environ.setdefault("DEMO_MODE", "true")
os.environ["GEMINI_API_KEY"] = ""  # tests never call Gemini
os.environ["DOTENV_DISABLED"] = "1"

from loopcloser.config import load_config  # noqa: E402
from loopcloser.domain.events import Actor  # noqa: E402
from loopcloser.domain.roles import Role  # noqa: E402
from loopcloser.pathways.library import default_library  # noqa: E402
from loopcloser.store.memory import MemoryRepository  # noqa: E402

NOW = datetime(2026, 10, 17, 2, 0, tzinfo=UTC)


@pytest.fixture
def repo():
    return MemoryRepository()


@pytest.fixture
def lib():
    return default_library()


@pytest.fixture
def coord():
    return Actor(id="coord-01", role=Role.COORDINATOR)


@pytest.fixture
def supervisor():
    return Actor(id="sup-01", role=Role.SUPERVISOR)


@pytest.fixture
def worker():
    return Actor(id="worker-01", role=Role.WORKER)


def screening(**kw):
    base = {
        "participant_id": "P-000042",
        "screening_id": "S-1",
        "screening_type": "fit",
        "result": "positive",
        "severity": "abnormal",
        "screened_at": "2026-10-10",
        "red_flag": False,
    }
    base.update(kw)
    return base


@pytest.fixture
def make_cfg(monkeypatch):
    def _make(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return load_config()

    return _make
