from typing import Optional, List
from sqlmodel import SQLModel, Field, create_engine, Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from hydra_reposter.core.config import settings

# Модель таблицы accounts
class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    phone: str
    proxy_id: Optional[int] = Field(default=None)
    status: str
    session_path: str
    item_id: int

engine = create_engine(settings.DB_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db() -> None:
    SQLModel.metadata.create_all(engine)

def get_session() -> Session:
    return SessionLocal()