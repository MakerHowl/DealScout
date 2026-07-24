import os
import sys

# Add current directory to python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Set database URL to a test database
data_dir = os.path.join(current_dir, "data")
os.makedirs(data_dir, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(data_dir, 'test_deals_auth.db')}"

from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db

def test_auth_system():
    db_file = os.path.join(data_dir, 'test_deals_auth.db')
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
    print("Initializing test database...")
    init_db()
    
    # Use TestClient with automatic redirect following disabled for status code verification
    client = TestClient(app)

    print("1. Testing GET /login and GET /register pages...")
    resp = client.get("/login")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "Willkommen zurück!" in resp.text
    
    resp = client.get("/register")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "Konto erstellen" in resp.text
    print("-> Pages loaded successfully!")

    print("2. Testing User Registration (POST /register)...")
    test_email = "testuser@dealscout.de"
    test_pass = "SecurePass123!"
    
    resp = client.post(
        "/register",
        data={"email": test_email, "password": test_pass},
        follow_redirects=False
    )
    assert resp.status_code == 303, f"Expected 303 redirect after registration, got {resp.status_code}"
    assert "dealscout_auth" in resp.cookies, "dealscout_auth cookie missing after registration"
    print("-> User registration passed with cookie set!")

    print("3. Testing User Logout (GET /logout)...")
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303, f"Expected 303 redirect on logout, got {resp.status_code}"
    auth_cookie = resp.cookies.get("dealscout_auth")
    assert auth_cookie == "" or auth_cookie is None, "Cookie should be cleared on logout"
    print("-> Logout passed!")

    print("4. Testing User Login (POST /login)...")
    resp = client.post(
        "/login",
        data={"username": test_email, "password": test_pass},
        follow_redirects=False
    )
    assert resp.status_code == 303, f"Expected 303 redirect after login, got {resp.status_code}"
    assert "dealscout_auth" in resp.cookies, "dealscout_auth cookie missing after login"
    token = resp.cookies["dealscout_auth"]
    print("-> User login passed!")

    print("5. Testing unauthenticated page redirects to /login...")
    client_unauth = TestClient(app)
    for protected_url in ["/", "/favorites-offers", "/favorite-products", "/settings"]:
        resp = client_unauth.get(protected_url, follow_redirects=False)
        assert resp.status_code == 303, f"Expected 303 for {protected_url}, got {resp.status_code}"
        assert resp.headers.get("location") == "/login", f"Expected redirect to /login for {protected_url}"
    
    # Test HTMX unauthenticated request
    resp = client_unauth.post("/add-favorite-product", data={"name": "Kaffee"}, headers={"HX-Request": "true"}, follow_redirects=False)
    assert resp.status_code == 401, f"Expected 401 for unauthenticated HTMX request, got {resp.status_code}"
    assert resp.headers.get("HX-Redirect") == "/login", "Expected HX-Redirect to /login"
    print("-> Unauthenticated page and HTMX protection passed!")

    print("6. Testing authenticated actions (Favorites & Products)...")
    client_auth = TestClient(app, cookies={"dealscout_auth": token})

    # Add favorite product
    resp = client_auth.post("/add-favorite-product", data={"name": "Bio-Milch"})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "Erfolgreich hinzugefügt!" in resp.text

    # List favorite products
    resp = client_auth.get("/favorite-products-list")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "Bio-Milch" in resp.text
    print("-> Favorite products created and listed successfully!")

    # Toggle favorite market
    market_id = "test-edeka-123"
    resp = client_auth.post(
        "/toggle-favorite",
        data={
            "id": market_id,
            "name": "Edeka Testmarkt",
            "street": "Hauptstr. 1",
            "zip_code": "10115",
            "city": "Berlin",
            "url": "http://example.com",
            "offers_url": "http://example.com/offers"
        }
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    # Test user-bound Pushover settings
    resp = client_auth.post(
        "/settings/pushover",
        data={"user_key": "user_key_abc", "api_token": "token_xyz", "enabled": "true"}
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "erfolgreich gespeichert" in resp.text

    resp = client_auth.get("/settings")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "user_key_abc" in resp.text, "User-bound Pushover user_key missing from settings page"
    print("-> User-bound Pushover settings tested successfully!")

    print("\nALL AUTH & USER MANAGEMENT TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    try:
        test_auth_system()
        sys.exit(0)
    except AssertionError as e:
        print(f"\nTEST ASSERTION ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nTEST EXCEPTION: {e}")
        sys.exit(1)
