from pathlib import Path
from typing import Optional
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field as PydanticField, field_validator


class Settings(BaseSettings):
    # ----- Telegram ---------------------------------------------------------
    api_id: Optional[int] = PydanticField(None, alias="API_ID")
    api_hash: Optional[str] = PydanticField(None, alias="API_HASH")

    # ----- Покупка аккаунтов -----------------------------------------------------
    lolz_token: Optional[str] = PydanticField(None, alias="LOLZ_API_KEY")

    # Back‑compat: allow referencing `settings.lolz_api_key`
    @property
    def lolz_api_key(self) -> Optional[str]:
        """Alias that mirrors *lolz_token* so old code keeps working."""
        return self.lolz_token

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

    # ─── Proxy‑Seller ────────────────────────
    # store static defaults once; we’ll expose dynamic getters below
    proxyseller_token_static: str | None = PydanticField(
        None, alias="PROXYSELLER_TOKEN"
    )
    proxyseller_id_static: int | None = PydanticField(
        None, alias="PROXYSELLER_ID"
    )

    # --- Dynamic env accessors for tests & runtime overrides -------------------
    @property
    def proxyseller_token(self) -> str | None:  # noqa: D401
        """
        Return the *current* ``PROXYSELLER_TOKEN`` from the environment
        or fall back to the value loaded at instantiation time.
        """
        return os.getenv("PROXYSELLER_TOKEN") or self.proxyseller_token_static

    @property
    def proxyseller_id(self) -> int | None:  # noqa: D401
        """
        Same idea as :pyattr:`proxyseller_token`, but coercing to ``int``.
        """
        env_val = os.getenv("PROXYSELLER_ID")
        return int(env_val) if env_val is not None else self.proxyseller_id_static

    # ----- Директории и тайминги --------------------------------------------
    default_delay: float = PydanticField(1.0, alias="DEFAULT_DELAY")
    floodwait_threshold: int = PydanticField(1800, alias="FLOODWAIT_THRESHOLD")
    peerflood_threshold: int = PydanticField(3, alias="PEERFLOOD_THRESHOLD")

    # ----- Дополнительные параметры -----------------------------------------
    device_model: str = PydanticField("HydraReposter", alias="DEVICE_MODEL")
    lolz_api_base_url: str = PydanticField(
        "https://api.lzt.market", alias="LOLZ_API_BASE_URL"
    )
    log_level: str = PydanticField("INFO", alias="LOG_LEVEL")
    debug: bool = PydanticField(False, alias="DEBUG")

    # ----- Конфиг Pydantic --------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )


settings = Settings()  # Singleton used across the project

def refresh_settings() -> None:
    """
    Re‑instantiate the global :pydata:`~hydra_reposter.core.config.settings`
    after test code mutates environment variables.
    """
    global settings  # noqa: PLW0603
    settings = Settings()
