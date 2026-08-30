from app.redis.redis_client import redis_client

async def set_cache(short_code:str,short_url):
    await redis_client.set(short_code,short_url)