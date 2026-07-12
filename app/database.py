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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationship back to market
    market: Market = Relationship(back_populates="offers")

class FavoriteProduct(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

def init_db():
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if inspector.has_table("offer"):
        pks = inspector.get_pk_constraint("offer").get("constrained_columns", [])
        if len(pks) < 2:
            print("Old database schema detected (no composite PK). Recreating tables...")
            SQLModel.metadata.drop_all(engine)
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
