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

    print("7. Testing Admin User Management & Promotion Logic...")
    # First user (testuser@dealscout.de) must be superuser
    resp_admin = client_auth.get("/admin/users")
    assert resp_admin.status_code == 200, f"Expected 200 for Admin on /admin/users, got {resp_admin.status_code}"
    assert "Userverwaltung" in resp_admin.text
    assert "Administrator" in resp_admin.text
    print("-> First user is Admin and can access /admin/users!")

    # Register a second user (user2@dealscout.de)
    resp2 = client.post(
        "/register",
        data={"email": "user2@dealscout.de", "password": "UserPass123!"},
        follow_redirects=False
    )
    token2 = resp2.cookies["dealscout_auth"]
    client_user2 = TestClient(app, cookies={"dealscout_auth": token2})

    # Second user must NOT be superuser and must be blocked from /admin/users
    resp2_admin = client_user2.get("/admin/users", follow_redirects=False)
    assert resp2_admin.status_code == 303, f"Expected 303 redirect for non-admin on /admin/users, got {resp2_admin.status_code}"
    assert resp2_admin.headers.get("location") == "/", "Expected redirect to / for non-admin"
    print("-> Second user is non-admin and blocked from /admin/users!")

    # Test Admin toggling user2 role to Admin, then back to User
    from sqlmodel import Session, select
    from app.database import engine, User
    with Session(engine) as session:
        u2 = session.exec(select(User).where(User.email == "user2@dealscout.de")).first()
        assert u2 is not None, "user2 should exist in database"
        assert not u2.is_superuser, "user2 should initially not be superuser"
        u2_id = str(u2.id)

    # 1. Promote user2 to Admin
    toggle_resp = client_auth.post(f"/admin/users/{u2_id}/toggle-role")
    assert toggle_resp.status_code == 200, f"Expected 200 on toggle-role, got {toggle_resp.status_code}"
    with Session(engine) as session:
        u2_promoted = session.exec(select(User).where(User.email == "user2@dealscout.de")).first()
        assert u2_promoted.is_superuser, "user2 should be promoted to superuser"
    print("-> Admin promoted user2 to Administrator successfully!")

    # 2. Demote user2 back to regular User
    toggle_resp2 = client_auth.post(f"/admin/users/{u2_id}/toggle-role")
    assert toggle_resp2.status_code == 200, f"Expected 200 on toggle-role demote, got {toggle_resp2.status_code}"
    with Session(engine) as session:
        u2_demoted = session.exec(select(User).where(User.email == "user2@dealscout.de")).first()
        assert not u2_demoted.is_superuser, "user2 should be demoted back to regular user"
    print("-> Admin demoted user2 back to regular User successfully!")

    # Admin deletes second user
    del_resp = client_auth.delete(f"/admin/users/{u2_id}")
    assert del_resp.status_code == 200, f"Expected 200 on delete_user, got {del_resp.status_code}"

    with Session(engine) as session:
        u2_check = session.exec(select(User).where(User.email == "user2@dealscout.de")).first()
        assert u2_check is None, "user2 should have been deleted from database"
    print("-> Admin user deletion passed successfully!")

    print("8. Testing Password Change...")
    # 1. Invalid current password
    pwd_err1 = client_auth.post(
        "/settings/change-password",
        data={"current_password": "WrongPassword123!", "new_password": "NewSecret123!", "confirm_password": "NewSecret123!"}
    )
    assert pwd_err1.status_code == 200, f"pwd_err1 status {pwd_err1.status_code}"
    assert "falsch" in pwd_err1.text.lower(), f"pwd_err1 text: {pwd_err1.text}"

    # 2. Mismatched passwords
    pwd_err2 = client_auth.post(
        "/settings/change-password",
        data={"current_password": "SecurePass123!", "new_password": "NewSecret123!", "confirm_password": "DifferentPass123!"}
    )
    assert pwd_err2.status_code == 200, f"pwd_err2 status {pwd_err2.status_code}"
    assert "stimmen nicht überein" in pwd_err2.text.lower(), f"pwd_err2 text: {pwd_err2.text}"

    # 3. Successful password change
    pwd_ok = client_auth.post(
        "/settings/change-password",
        data={"current_password": "SecurePass123!", "new_password": "NewSecret123!", "confirm_password": "NewSecret123!"}
    )
    assert pwd_ok.status_code == 200, f"pwd_ok status {pwd_ok.status_code}"
    assert "erfolgreich geändert" in pwd_ok.text.lower(), f"pwd_ok text: {pwd_ok.text}"

    # 4. Verify login with new password
    login_new = client.post(
        "/login",
        data={"username": "testuser@dealscout.de", "password": "NewSecret123!"},
        follow_redirects=False
    )
    assert login_new.status_code == 303, f"Expected 303 redirect on login with new password, got {login_new.status_code}"
    print("-> Password change and login with new password verified successfully!")

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
