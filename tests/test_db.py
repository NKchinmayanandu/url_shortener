import uuid
import pytest

from sqlalchemy import insert

from app.db.shard import get_shard
from app.db.session import session_makers
from app.models.urls import Url
from app.repository.url_repository import get_url


@pytest.mark.asyncio
async def test_get_url_from_db():
    short_code = uuid.uuid4().hex[:5]
    original_url = "https://github.com"

    shard = get_shard(short_code)

    async with session_makers[shard]() as db:
        await db.execute(
            insert(Url).values(
                short_code=short_code,
                original_url=original_url,
            )
        )
        await db.commit()

    result = await get_url(short_code=short_code,shard=shard)

    assert result is not None
    assert result == original_url