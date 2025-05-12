from typing import Optional, List
from sqlmodel import SQLModel, Field, create_engine, Session

# Модель таблицы accounts
class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    phone: str
    proxy_id: Optional[int] = Field(default=None)
    status: str
    session_path: str
    item_id: int

# Подключение к БД
from hydra_reposter.core.config import settings
DB_URL = settings.db_url or f"sqlite:///{settings.sessions_dir}/accounts.db"
engine = create_engine(DB_URL, echo=False)

def init_db() -> None:
    SQLModel.metadata.create_all(engine)

def get_session() -> Session:
    return Session(engine)