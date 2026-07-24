import os
import json
import uuid
from typing import Optional, List
from datetime import datetime
from sqlmodel import Field, SQLModel, create_engine, Session, Relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, relationship
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID, SQLAlchemyBaseOAuthAccountTableUUID

# Define the database URLs (SQLite sync + async)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/deals.db")

# Create parent directories for database if they don't exist
db_path = DATABASE_URL.replace("sqlite:///", "")
if db_path.startswith("/"):
    db_path = "/" + db_path.lstrip("/")
os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

ASYNC_DATABASE_URL = DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///")
async_engine = create_async_engine(ASYNC_DATABASE_URL, connect_args={"check_same_thread": False})
async_session_maker = async_sessionmaker(async_engine, expire_on_commit=False)

class Base(DeclarativeBase):
    metadata = SQLModel.metadata

class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    pass

class User(SQLAlchemyBaseUserTableUUID, Base):
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship("OAuthAccount", lazy="joined")

class Market(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    street: str
    zip_code: str
    city: str
    url: str
    offers_url: str
    last_scraped: Optional[datetime] = Field(default=None)
    is_favorite: bool = Field(default=False)
    
    # Relationship to offers
    offers: List["Offer"] = Relationship(back_populates="market", cascade_delete=True)

class Offer(SQLModel, table=True):
    id: str = Field(primary_key=True)
    market_id: str = Field(foreign_key="market.id", primary_key=True)
    title: str = Field(index=True)
    price: Optional[float] = None
    app_price: Optional[float] = None
    discount_percentage: Optional[int] = None
    image_url: Optional[str] = None
    description: Optional[str] = None
    base_price: Optional[str] = None
    badge: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationship back to market
    market: Market = Relationship(back_populates="offers")

class FavoriteProduct(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: uuid.UUID = Field(index=True)
    name: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class UserMarketFavorite(SQLModel, table=True):
    user_id: uuid.UUID = Field(primary_key=True)
    market_id: str = Field(foreign_key="market.id", primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class NotificationConfig(SQLModel, table=True):
    user_id: uuid.UUID = Field(primary_key=True)
    service_name: str = Field(primary_key=True)
    enabled: bool = Field(default=False)
    settings_data: str = Field(default="{}")

    @property
    def settings(self) -> dict:
        try:
            return json.loads(self.settings_data)
        except Exception:
            return {}

    @settings.setter
    def settings(self, val: dict):
        self.settings_data = json.dumps(val)

def get_notification_config(session: Session, user_id: uuid.UUID, service_name: str) -> NotificationConfig:
    config = session.get(NotificationConfig, (user_id, service_name))
    if not config:
        config = NotificationConfig(user_id=user_id, service_name=service_name, enabled=False, settings_data="{}")
        session.add(config)
        session.commit()
        session.refresh(config)
    return config

class AppSetting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str

def get_setting(session: Session, key: str, default: str) -> str:
    setting = session.get(AppSetting, key)
    if not setting:
        setting = AppSetting(key=key, value=default)
        session.add(setting)
        session.commit()
        session.refresh(setting)
    return setting.value

def set_setting(session: Session, key: str, value: str):
    setting = session.get(AppSetting, key)
    if not setting:
        setting = AppSetting(key=key, value=value)
    else:
        setting.value = value
    session.add(setting)
    session.commit()

def init_db():
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    
    if inspector.has_table("favoriteproduct"):
        columns = [c["name"] for c in inspector.get_columns("favoriteproduct")]
        if "user_id" not in columns:
            print("Migration: Recreating favoriteproduct table with user_id column...")
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE favoriteproduct"))
                
    if inspector.has_table("notificationconfig"):
        columns = [c["name"] for c in inspector.get_columns("notificationconfig")]
        if "user_id" not in columns:
            print("Migration: Recreating notificationconfig table with user_id column...")
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE notificationconfig"))
                
    SQLModel.metadata.create_all(engine)

    # Promote all existing users to superusers for existing installations
    if inspector.has_table("user"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE user SET is_superuser = 1 WHERE is_superuser = 0 OR is_superuser IS NULL"))

def get_session():
    with Session(engine) as session:
        yield session

async def get_async_session():
    async with async_session_maker() as session:
        yield session
