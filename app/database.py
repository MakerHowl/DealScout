import os
from typing import Optional, List
from datetime import datetime
from sqlmodel import Field, SQLModel, create_engine, Session, Relationship

# Define the database URL (default to SQLite in the local data directory)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/deals.db")

# Create parent directories for database if they don't exist
db_path = DATABASE_URL.replace("sqlite:///", "")
# Handle absolute paths with 4 slashes: sqlite:////app/data/deals.db
if db_path.startswith("/"):
    db_path = "/" + db_path.lstrip("/")
os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

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

import json

class FavoriteProduct(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class NotificationConfig(SQLModel, table=True):
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

def get_notification_config(session: Session, service_name: str) -> NotificationConfig:
    config = session.get(NotificationConfig, service_name)
    if not config:
        config = NotificationConfig(service_name=service_name, enabled=False, settings_data="{}")
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
    if inspector.has_table("offer"):
        pks = inspector.get_pk_constraint("offer").get("constrained_columns", [])
        if len(pks) < 2:
            print("Old database schema detected (no composite PK). Recreating tables...")
            SQLModel.metadata.drop_all(engine)
        else:
            columns = [c["name"] for c in inspector.get_columns("offer")]
            with engine.begin() as conn:
                if "valid_from" not in columns:
                    print("Adding valid_from column to offer table...")
                    conn.execute(text("ALTER TABLE offer ADD COLUMN valid_from VARCHAR"))
                if "valid_until" not in columns:
                    print("Adding valid_until column to offer table...")
                    conn.execute(text("ALTER TABLE offer ADD COLUMN valid_until VARCHAR"))
    SQLModel.metadata.create_all(engine)
    
    # Check if is_favorite column exists in market table
    if inspector.has_table("market"):
        columns = [c["name"] for c in inspector.get_columns("market")]
        if "is_favorite" not in columns:
            print("Adding is_favorite column to market table...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE market ADD COLUMN is_favorite BOOLEAN DEFAULT 0"))

def get_session():
    with Session(engine) as session:
        yield session
