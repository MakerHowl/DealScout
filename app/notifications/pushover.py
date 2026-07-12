import httpx
from typing import List, Dict, Any
from app.notifications.base import NotificationService

class PushoverService(NotificationService):
    def send_test(self, settings: dict) -> bool:
        user_key = settings.get("user_key", "").strip()
        api_token = settings.get("api_token", "").strip()
        if not user_key or not api_token:
            print("Pushover test failed: missing credentials")
            return False
        
        url = "https://api.pushover.net/1/messages.json"
        payload = {
            "token": api_token,
            "user": user_key,
            "title": "DealScout Test",
            "message": "Pushover-Verbindung erfolgreich eingerichtet! 🎉"
        }
        try:
            response = httpx.post(url, data=payload, timeout=10)
            if response.status_code == 200:
                return True
            print(f"Pushover test failed: HTTP {response.status_code} - {response.text}")
            return False
        except Exception as e:
            print(f"Pushover test exception: {e}")
            return False

    def send_digest(self, settings: dict, market_name: str, offers: List[Dict[str, Any]]) -> bool:
        user_key = settings.get("user_key", "").strip()
        api_token = settings.get("api_token", "").strip()
        if not user_key or not api_token:
            print("Pushover send_digest failed: missing credentials")
            return False

        # Format message
        lines = [f"Neue Angebote bei {market_name}:", ""]
        for offer in offers:
            price_str = f"{offer['price']:.2f} €" if offer.get("price") is not None else ""
            app_price_str = f" (App: {offer['app_price']:.2f} €)" if offer.get("app_price") is not None else ""
            price_display = f" für {price_str}{app_price_str}" if price_str or app_price_str else ""
            lines.append(f"• {offer['title']}{price_display}")
            
        message = "\n".join(lines)
        url = "https://api.pushover.net/1/messages.json"
        payload = {
            "token": api_token,
            "user": user_key,
            "title": "DealScout: Neue Angebote!",
            "message": message
        }
        try:
            response = httpx.post(url, data=payload, timeout=10)
            if response.status_code == 200:
                return True
            print(f"Pushover send_digest failed: HTTP {response.status_code} - {response.text}")
            return False
        except Exception as e:
            print(f"Pushover send_digest exception: {e}")
            return False
