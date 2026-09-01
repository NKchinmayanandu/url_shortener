from app.db.session import async_sessionmaker
from app.models.urls import Url
from sqlalchemy import select
async def add_shortend_url(shard:int,short_code:str,url:str):
    async with async_sessionmaker[shard]() as db:
        url_record = Url(
            short_code=short_code,
            original_url=url
        )
        db.add(url_record)
        await db.commit()


async def get_url(shard: int, short_code: str):
    async with async_sessionmaker[shard]() as db:
        result = await db.execute(
            select(Url).where(Url.short_code == short_code)
        )

        url = result.scalar_one_or_none()

    return url.original_url if url else None
