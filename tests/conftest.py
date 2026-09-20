import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from app.main import app
from app.core.config import settings
from app.redis import cache


@pytest_asyncio.fixture
async def test_redis():
    redis = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )

    yield redis

    await redis.aclose()


@pytest_asyncio.fixture
async def client(test_redis, monkeypatch):
    monkeypatch.setattr(
        cache,
        "redis_client",
        test_redis,
    )

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client