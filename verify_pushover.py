import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add current directory to python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Set database URL to a test database
data_dir = os.path.join(current_dir, "data")
os.makedirs(data_dir, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(data_dir, 'test_deals_pushover.db')}"

from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.main import app
from app.database import init_db, Market, Offer, FavoriteProduct, NotificationConfig, get_notification_config, AppSetting, engine
from app.notifications.manager import get_service, notify_new_offers

class TestPushoverIntegration(unittest.TestCase):
    def setUp(self):
        init_db()
        self.client = TestClient(app)
        
        # Clean up database
        with Session(engine) as session:
            session.exec(select(Market)).all()
            for m in session.exec(select(Market)).all():
                session.delete(m)
            for o in session.exec(select(Offer)).all():
                session.delete(o)
            for p in session.exec(select(FavoriteProduct)).all():
                session.delete(p)
            for c in session.exec(select(NotificationConfig)).all():
                session.delete(c)
            for a in session.exec(select(AppSetting)).all():
                session.delete(a)
            session.commit()

    def test_database_and_registry(self):
        print("Testing NotificationConfig model...")
        with Session(engine) as session:
            config = get_notification_config(session, "pushover")
            self.assertIsNotNone(config)
            self.assertEqual(config.service_name, "pushover")
            self.assertEqual(config.enabled, False)
            self.assertEqual(config.settings, {})

            # Modify settings
            config.settings = {"user_key": "user123", "api_token": "tokenabc"}
            session.add(config)
            session.commit()

        # Re-fetch
        with Session(engine) as session:
            config = get_notification_config(session, "pushover")
            self.assertEqual(config.settings.get("user_key"), "user123")
            self.assertEqual(config.settings.get("api_token"), "tokenabc")
            
        print("Testing Service Registry...")
        service = get_service("pushover")
        self.assertIsNotNone(service)
        
    def test_settings_routes(self):
        print("Testing GET /settings...")
        res = self.client.get("/settings")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Einstellungen & Benachrichtigungen", res.text)
        self.assertIn("Pushover-Integration", res.text)

        print("Testing POST /settings/pushover...")
        res = self.client.post("/settings/pushover", data={
            "user_key": "test_user_key",
            "api_token": "test_api_token",
            "enabled": "true"
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn("erfolgreich gespeichert", res.text)

        # Verify DB changed
        with Session(engine) as session:
            config = get_notification_config(session, "pushover")
            self.assertEqual(config.enabled, True)
            self.assertEqual(config.settings.get("user_key"), "test_user_key")
            self.assertEqual(config.settings.get("api_token"), "test_api_token")

    @patch("httpx.post")
    def test_settings_test_route(self, mock_post):
        print("Testing POST /settings/pushover/test...")
        
        # Configure mock for successful HTTP call
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        res = self.client.post("/settings/pushover/test", data={
            "user_key": "some_user",
            "api_token": "some_token"
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn("Test-Benachrichtigung erfolgreich gesendet", res.text)
        
        # Verify httpx.post was called with the correct params
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.pushover.net/1/messages.json")
        self.assertEqual(kwargs["data"]["user"], "some_user")
        self.assertEqual(kwargs["data"]["token"], "some_token")

    @patch("app.notifications.pushover.PushoverService.send_digest")
    def test_scraper_notification_trigger(self, mock_send_digest):
        print("Testing scraper notification trigger...")
        mock_send_digest.return_value = True

        with Session(engine) as session:
            # Enable Pushover
            config = get_notification_config(session, "pushover")
            config.enabled = True
            config.settings = {"user_key": "u_scraped", "api_token": "t_scraped"}
            session.add(config)

            # Add favorite product
            prod = FavoriteProduct(name="Coca-Cola")
            session.add(prod)

            # Add market
            market = Market(
                id="market-test",
                name="Edeka Testmarkt",
                street="Teststr. 10",
                zip_code="54321",
                city="Teststadt",
                url="http://test.url",
                offers_url="http://test.url/offers"
            )
            session.add(market)
            session.commit()

        # Let's mock scrape_edeka_offers to return new offers (one matching "Coca-Cola")
        mock_scraped_offers = [
            {
                "id": "scraped-offer-1",
                "title": "Coca-Cola 1.5L",
                "price": 1.19,
                "app_price": 0.99,
                "discount_percentage": 20,
                "image_url": "http://image.url/cola",
                "description": "Erfrischungsgetränk",
                "base_price": "1 L = 0.79 €",
                "badge": "Knüller"
            },
            {
                "id": "scraped-offer-2",
                "title": "Milch 1L",
                "price": 0.99,
                "app_price": None,
                "discount_percentage": None,
                "image_url": "http://image.url/milch",
                "description": "Frische Vollmilch",
                "base_price": None,
                "badge": ""
            }
        ]

        with patch("app.scraper.scrape_edeka_offers", return_value=mock_scraped_offers):
            from app.scraper import update_market_offers_in_db
            with Session(engine) as session:
                success = update_market_offers_in_db("market-test", session)
                self.assertTrue(success)

        # Verify notify_new_offers was triggered, calling send_digest
        mock_send_digest.assert_called_once()
        args = mock_send_digest.call_args[0]
        settings = args[0]
        market_name = args[1]
        offers = args[2]

        self.assertEqual(settings.get("user_key"), "u_scraped")
        self.assertEqual(market_name, "Edeka Testmarkt")
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["title"], "Coca-Cola 1.5L")

        print("Scraper trigger test PASSED.")

    def test_settings_cron_route(self):
        print("Testing POST /settings/cron with valid expression...")
        res = self.client.post("/settings/cron", data={"cron": "0 12 * * *"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("erfolgreich gespeichert", res.text)
        self.assertIn("hx-swap-oob", res.text)

        # Verify DB value
        with Session(engine) as session:
            from app.database import get_setting
            cron_val = get_setting(session, "refresh_cron", "")
            self.assertEqual(cron_val, "0 12 * * *")

        print("Testing POST /settings/cron with invalid expression...")
        res = self.client.post("/settings/cron", data={"cron": "invalid expression"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("Ungültiger Cron-Ausdruck", res.text)

        # Verify DB value did not change
        with Session(engine) as session:
            cron_val = get_setting(session, "refresh_cron", "")
            self.assertEqual(cron_val, "0 12 * * *")

    @patch("app.scraper.update_market_offers_in_db")
    def test_scheduler_cron_logic(self, mock_update_db):
        print("Testing background cron scheduler logic...")
        mock_update_db.return_value = True

        from app.database import set_setting
        from app.scheduler import run_automatic_refresh
        
        # Test case 1: No last run
        with Session(engine) as session:
            # Set cron to midnight daily
            set_setting(session, "refresh_cron", "0 0 * * *")
            
            # Setup favorite market
            market = Market(
                id="sched-test-market",
                name="Edeka Sched",
                street="Schedstr. 1",
                zip_code="12345",
                city="Muster",
                url="http://test.sched",
                offers_url="http://test.sched/offers",
                is_favorite=True
            )
            session.add(market)
            session.commit()

        # Run scheduler check; since there's no last run, it should trigger immediately
        run_automatic_refresh()
        mock_update_db.assert_called_once()
        
        # Reset mock
        mock_update_db.reset_mock()

        # Test case 2: Last run was 5 minutes ago, cron is daily at midnight
        # Next run is tonight, so it should NOT trigger now.
        with Session(engine) as session:
            from app.database import get_setting
            last_run_str = get_setting(session, "last_automatic_refresh", "")
            self.assertTrue(bool(last_run_str)) # Confirms it was set in Case 1
            
        run_automatic_refresh()
        mock_update_db.assert_not_called()

        # Test case 3: Cron is every 5 minutes ("*/5 * * * *") and last run was 10 minutes ago
        # It should trigger now.
        from datetime import datetime, timedelta
        ten_minutes_ago = (datetime.utcnow() - timedelta(minutes=10)).isoformat()
        with Session(engine) as session:
            set_setting(session, "refresh_cron", "*/5 * * * *")
            set_setting(session, "last_automatic_refresh", ten_minutes_ago)
            
        run_automatic_refresh()
        mock_update_db.assert_called_once()

if __name__ == "__main__":
    unittest.main()
