from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    POSTGRES_USER : str = "chinmay"
    POSTGRES_PASSWORD : int
    POSTGRES_DB : str
    DATABASE_URL0 : str
    DATABASE_URL1 : str
    DATABASE_URL2 : str
    REDIS_URL : str = "redis://localhost:6379"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    @property
    def async_database_url(self) -> str:
        return self.DATABASE_URL.replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )
settings = Settings()
