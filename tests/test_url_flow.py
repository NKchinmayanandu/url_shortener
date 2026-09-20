import pytest
from app.redis import cache


@pytest.mark.asyncio
async def test_shorten_and_redirect_flow(client, test_redis, monkeypatch):
    monkeypatch.setattr(
        cache,
        "redis_client",
        test_redis,
    )

    original_url = "https://github.com"

    response = await client.post(
        "/shorten",
        params={"url": original_url},
    )

    assert response.status_code == 200

    short_code = response.json()["short_code"]

    response = await client.get(
        f"/{short_code}",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == original_url