import os
import sys

# Add current directory to python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Set database URL to a test database in the data directory
data_dir = os.path.join(current_dir, "data")
os.makedirs(data_dir, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(data_dir, 'test_deals.db')}"

from sqlmodel import Session, select
from app.database import init_db, Market, engine

def test_migration_and_favorites():
    print("Testing database initialization and schema migration...")
    init_db()
    print("Database initialized successfully.")

    with Session(engine) as session:
        test_id = "test-market-1"
        
        # Clean up any old test record
        old_market = session.get(Market, test_id)
        if old_market:
            session.delete(old_market)
            session.commit()
            
        print("Inserting test market...")
        market = Market(
            id=test_id,
            name="Test Edeka Market",
            street="Hauptstr. 1",
            zip_code="12345",
            city="Musterstadt",
            url="http://example.com/test",
            offers_url="http://example.com/test/angebote"
        )
        session.add(market)
        session.commit()
        session.refresh(market)
        
        assert market.is_favorite == False, "Default value of is_favorite should be False"
        print("Test market inserted successfully with is_favorite=False.")
        
        print("Toggling is_favorite status to True...")
        market.is_favorite = True
        session.add(market)
        session.commit()
        
    with Session(engine) as session2:
        queried_market = session2.get(Market, test_id)
        assert queried_market is not None, "Failed to retrieve market"
        assert queried_market.is_favorite == True, "Failed to persist is_favorite status"
        print("Verification SUCCESS: is_favorite status successfully persisted in database!")
        
        # Clean up
        session2.delete(queried_market)
        session2.commit()
        print("Cleanup completed.")

if __name__ == "__main__":
    try:
        test_migration_and_favorites()
        print("ALL TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)
    except AssertionError as e:
        print(f"TEST ASSERTION ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"TEST EXCEPTION: {e}")
        sys.exit(1)
