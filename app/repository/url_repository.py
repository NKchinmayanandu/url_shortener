from app.db.session import async_sessionmaker
from app.models.urls import Url
async def add_shortend_url(shard:int,short_code:str,url:str):
    async with async_sessionmaker[shard]() as db:
        url_record = Url(
            short_code=short_code,
            original_url=url
        )
        db.add(url_record)
        await db.commit()



