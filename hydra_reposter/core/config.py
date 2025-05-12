from pathlib import Path
from sqlmodel import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, ConfigDict, field_validator
from typing import Optional

class Settings(BaseSettings):
    # ----- Telegram ---------------------------------------------------------
    api_id: Optional[int] = Field(None, alias="API_ID")
    api_hash: Optional[str] = Field(None, alias="API_HASH")

    # ----- Покупка аккаунтов -----------------------------------------------------
    lolz_token: Optional[str] = Field(None, alias="LOLZ_TOKEN")
    market_item_id: int = Field(..., env="MARKET_ITEM_ID")
    market_price: float = Field(0.5, env="MARKET_PRICE")

    @field_validator("market_item_id", mode="after")
    def _coerce_market_item_id(cls, v):
        try:
            return int(v)
        except (TypeError, ValueError):
            # если в .env опечатка (например "telegram") → переключаемся на автопоиск
            return 0

    # ----- Прокси AnyIp -----------------------------------------------------
    anyip_username: str | None = None
    anyip_password: str | None = None
    anyip_proxy_host: str | None = None
    anyip_proxy_port: int | None = 1080

    # ─── Proxy-Seller ────────────────────────
    proxyseller_token: str | None = None
    proxyseller_id: int | None = None

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")

    # ----- Директории и тайминги --------------------------------------------
    sessions_dir: Path = Field("sessions", alias="SESSIONS_DIR")
    db_url: Optional[str] = Field(None, env="DB_URL")
    default_delay: float = Field(1.0, alias="DEFAULT_DELAY")
    floodwait_threshold: int = Field(1800, alias="FLOODWAIT_THRESHOLD")
    peerflood_threshold: int = Field(3, alias="PEERFLOOD_THRESHOLD")

    # ----- Конфиг Pydantic --------------------------------------------------
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

settings = Settings()