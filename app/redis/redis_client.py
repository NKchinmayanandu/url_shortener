from app.core.config import settings
from redis.asyncio import Redis

redis_client = Redis.from_url(
    settings.REDIS_URL,
    decode_responses=True
)

