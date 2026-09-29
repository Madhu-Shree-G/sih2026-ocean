"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402


def _has_demo_data() -> bool:
    return any(settings.zarr_dir.glob("*.zarr")) if settings.zarr_dir.exists() else False


requires_data = pytest.mark.skipif(
    not _has_demo_data(),
    reason="Demo dataset missing. Run: python scripts/generate_sample_data.py",
)


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    """A TestClient with the application lifespan actually executed."""
    with TestClient(app) as test_client:
        # Rate limiting would otherwise make the suite order-dependent.
        test_client.app.state.rate_limiter.enabled = False
        yield test_client


@pytest.fixture(scope="session")
def dataset_id(client: TestClient) -> str:
    payload = client.get("/api/v1/health/ready").json()
    datasets = payload.get("datasets") or []
    if not datasets:
        pytest.skip("No datasets loaded.")
    return datasets[0]


@pytest.fixture(scope="session")
def profile_id(client: TestClient) -> int:
    payload = client.get("/api/v1/observations/profiles?limit=1").json()
    profiles = payload.get("profiles") or []
    if not profiles:
        pytest.skip("No observation profiles loaded.")
    return int(profiles[0]["profile_id"])
