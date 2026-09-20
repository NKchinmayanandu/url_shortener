
import pytest
from app.redis import cache



@pytest.mark.asyncio
async def test_set_and_get_cache(test_redis, monkeypatch):
    monkeypatch.setattr(
        cache,
        "redis_client",
        test_redis,
    )

    short_code = "abc12"
    url = "https://github.com"

    await cache.set_cache(short_code, url)

    result = await cache.get_cache(short_code)

    assert result == url


@pytest.mark.asyncio
async def test_cache_has_ttl(test_redis, monkeypatch):
    monkeypatch.setattr(
        cache,
        "redis_client",
        test_redis,
    )

    short_code = "ttl12"
    url = "https://github.com"

    await cache.set_cache(short_code, url)

    ttl = await test_redis.ttl(short_code)

    assert 0 < ttl <= 300

