from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field as PydanticField, field_validator

class Settings(BaseSettings):
    # ----- Telegram ---------------------------------------------------------
    api_id: Optional[int] = PydanticField(None, alias="API_ID")
    api_hash: Optional[str] = PydanticField(None, alias="API_HASH")

    # ----- Покупка аккаунтов -----------------------------------------------------
    lolz_token: Optional[str] = PydanticField(None, alias="LOLZ_TOKEN")
    market_item_id: int = PydanticField(..., env="MARKET_ITEM_ID")
    market_price: float = PydanticField(0.5, env="MARKET_PRICE")

    sessions_dir: Path = PydanticField(Path("sessions"), alias="SESSIONS_DIR")
    db_url: Optional[str] = PydanticField(None, alias="DB_URL")

    @property
    def DB_URL(self) -> str:
        return self.db_url or f"sqlite:///{self.sessions_dir}/accounts.db"

    @field_validator("market_item_id", mode="after")
    def _coerce_market_item_id(cls, v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    # ----- Прокси AnyIp -----------------------------------------------------
    anyip_username: str | None = None
    anyip_password: str | None = None
    anyip_proxy_host: str | None = None
    anyip_proxy_port: int | None = 1080

    # ─── Proxy-Seller ────────────────────────
    proxyseller_token: str | None = None
    proxyseller_id: int | None = None

    # ----- Директории и тайминги --------------------------------------------
    default_delay: float = PydanticField(1.0, alias="DEFAULT_DELAY")
    floodwait_threshold: int = PydanticField(1800, alias="FLOODWAIT_THRESHOLD")
    peerflood_threshold: int = PydanticField(3, alias="PEERFLOOD_THRESHOLD")

    # ----- Конфиг Pydantic --------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )


settings = Settings()