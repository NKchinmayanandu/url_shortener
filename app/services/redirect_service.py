from app.redis.cache import get_cache,set_cache
from app.db.shard import get_shard
from app.repository.url_repository import get_url
async def redirect_url(short_code:str):
    url = await get_cache(short_code=short_code)

    if url:
        return {"url":url}
    
    shard = await get_shard(short_code=short_code)

    url = await get_url(shard=shard,short_code=short_code)

    if not url:
        return None

    await set_cache(short_code=short_code,url=url)

    return {"url":url}



    