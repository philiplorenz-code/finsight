from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINSIGHT_", extra="ignore")
    database_url: str = Field(default="sqlite:///./finsight.db", validation_alias=AliasChoices("FINSIGHT_DATABASE_URL", "DATABASE_URL"))
    bootstrap_secret: str = ""
    cookie_secure: bool = True
    session_hours: int = 24
    max_upload_bytes: int = 16 * 1024 * 1024
    max_uncompressed_bytes: int = 64 * 1024 * 1024
    max_import_rows: int = 100000
    allowed_origins: list[str] = []
    # Development only: e-mail of the user signed in without a password from localhost. Empty = off.
    dev_login: str = ""


settings = Settings()
