from app.services.unique_code import generate_unique_code
from app.repository.url_repository import add_shortend_url
from app.db.shard import get_shard
from sqlalchemy.exc import IntegrityError
from app.schemas.shorten import ShortenResponse
from app.redis.cache import set_cache
import logging 

async def shorten_url(url:str):
    attempt = 0
    while attempt < 5:
        short_code = generate_unique_code()
        shard = get_shard(short_code=short_code)
        try:
            await add_shortend_url(shard=shard,short_code=short_code,url=url)
        except IntegrityError:
            attempt += 1
            logging.warning("could not able to generate differnt short_code")
            continue
        break
    else:
        logging.error(
            "Failed to generate a unique short_code after %d attempts",
            5,
            exc_info=True
        )
        raise RuntimeError("all attempts failed")

    try:
        await set_cache(short_code=short_code,url=url)
    except Exception:
        logging.warning(
            "Redis cache population failed for short_code=%s",
            short_code,
            exc_info=True,
        )

    return ShortenResponse(
    short_code=short_code,
    short_url=f"https://url.thechinmay/{short_code}",
    )


