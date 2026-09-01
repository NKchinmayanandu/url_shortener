from app.redis.redis_client import redis_client

async def set_cache(short_code:str,url:str):
    await redis_client.set(short_code,url=url)