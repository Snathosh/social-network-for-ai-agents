"""
Shared pytest fixtures for the AI Agent Social Network test suite.
Supports FastAPI TestClient with in-memory SQLite and mock embeddings.
"""
import uuid
import secrets
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db, AsyncSessionLocal
from app.models import Base, Agent, Subscription


@pytest.fixture
def client():
    """Synchronous FastAPI TestClient."""
    with TestClient(app) as test_client:
        yield test_client
