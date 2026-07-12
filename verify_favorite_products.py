import os
import sys

# Add current directory to python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Set database URL to a test database
data_dir = os.path.join(current_dir, "data")
os.makedirs(data_dir, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(data_dir, 'test_deals_favorites.db')}"

from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.main import app
from app.database import init_db, Market, Offer, FavoriteProduct, engine

def test_favorite_products():
    print("Initializing test database...")
    init_db()
    
    print("Setting up test market and offers...")
    market_id = "test-fav-prod-market"
    offer_id = "test-fav-offer-pizza"
    
    with Session(engine) as session:
        # Clean up any old test records
        for m in session.exec(select(Market).where(Market.id == market_id)).all():
            session.delete(m)
        for o in session.exec(select(Offer).where(Offer.market_id == market_id)).all():
            session.delete(o)
        for p in session.exec(select(FavoriteProduct)).all():
            session.delete(p)
        session.commit()
        
        # Add a favorite market
        market = Market(
            id=market_id,
            name="Edeka Altona",
            street="Musterstr. 2",
            zip_code="22767",
            city="Hamburg",
            url="http://example.com/altona",
            offers_url="http://example.com/altona/offers",
            is_favorite=True
        )
        session.add(market)
        
        # Add an offer matching "Wagner Tiefkühlpizza"
        offer = Offer(
            id=offer_id,
            market_id=market_id,
            title="Wagner Tiefkühlpizza Steinofen Speciale",
            price=1.99,
            description="Leckere Steinofenpizza",
            base_price="1 kg = 5.00 €",
            badge="Knüller"
        )
        session.add(offer)
        session.commit()
        
    client = TestClient(app)
    
    # 1. Verify GET /favorite-products renders page
    print("Testing GET /favorite-products...")
    res = client.get("/favorite-products")
    assert res.status_code == 200
    assert "Meine Lieblingsprodukte" in res.text
    
    # 2. Verify POST /add-favorite-product adds item
    print("Testing POST /add-favorite-product...")
    res = client.post("/add-favorite-product", data={"name": "Wagner Tiefkühlpizza"})
    assert res.status_code == 200
    assert "Erfolgreich hinzugefügt!" in res.text
    assert "HX-Trigger" in res.headers
    assert "update-favorite-products" in res.headers["HX-Trigger"]
    
    # 3. Verify duplicate check
    print("Testing duplicate check...")
    res = client.post("/add-favorite-product", data={"name": "Wagner Tiefkühlpizza"})
    assert res.status_code == 200
    assert "bereits in deiner Liste" in res.text
    
    # 4. Verify blank check
    print("Testing blank check...")
    res = client.post("/add-favorite-product", data={"name": "  "})
    assert res.status_code == 200
    assert "darf nicht leer sein" in res.text
    
    # 5. Verify GET /favorite-products-list contains item
    print("Testing GET /favorite-products-list...")
    res = client.get("/favorite-products-list")
    assert res.status_code == 200
    assert "Wagner Tiefkühlpizza" in res.text
    
    # 6. Verify GET /favorite-products-offers finds matching offer
    print("Testing GET /favorite-products-offers...")
    res = client.get("/favorite-products-offers")
    assert res.status_code == 200
    assert "Wagner Tiefkühlpizza Steinofen Speciale" in res.text
    assert "Edeka Altona" in res.text
    
    # 7. Test delete /delete-favorite-product/{id}
    print("Testing DELETE /delete-favorite-product/{id}...")
    with Session(engine) as session:
        prod = session.exec(select(FavoriteProduct).where(FavoriteProduct.name == "Wagner Tiefkühlpizza")).first()
        assert prod is not None
        prod_id = prod.id
        
    res = client.delete(f"/delete-favorite-product/{prod_id}")
    assert res.status_code == 200
    assert "HX-Trigger" in res.headers
    assert "update-favorite-products" in res.headers["HX-Trigger"]
    
    # 8. Verify product list is empty
    print("Testing list is empty after deletion...")
    res = client.get("/favorite-products-list")
    assert "Deine Liste ist noch leer" in res.text
    
    # 9. Verify offers are empty
    res = client.get("/favorite-products-offers")
    assert "Keine Lieblingsprodukte definiert" in res.text
    
    print("Verification SUCCESS: All tests passed!")
    
    # Clean up
    with Session(engine) as session:
        for m in session.exec(select(Market).where(Market.id == market_id)).all():
            session.delete(m)
        for o in session.exec(select(Offer).where(Offer.market_id == market_id)).all():
            session.delete(o)
        session.commit()

if __name__ == "__main__":
    try:
        test_favorite_products()
        sys.exit(0)
    except AssertionError as e:
        print(f"Assertion Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Exception: {e}")
        sys.exit(1)
