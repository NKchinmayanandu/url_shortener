from sqlalchemy.ext.asyncio import AsyncSession,async_sessionmaker, create_async_engine

from app.core.config import settings

engines = [
    create_async_engine(settings.POSTGRES_URL_0,
                        pool_size=10,max_overflow=20),
    create_async_engine(settings.POSTGRES_URL_1,pool_size=10,
                        max_overflow=20),
    create_async_engine(settings.POSTGRES_URL_2,pool_size=10,
                        max_overflow=20),
]


session_makers = [
    async_sessionmaker(engine, class_=AsyncSession)
    for engine in engines
]