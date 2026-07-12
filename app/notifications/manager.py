from typing import Dict, List, Any
from sqlmodel import Session, select
from app.database import NotificationConfig
from app.notifications.base import NotificationService
from app.notifications.pushover import PushoverService

# Registry mapping service identifier names to their implementations
SERVICES: Dict[str, NotificationService] = {
    "pushover": PushoverService()
}

def get_service(name: str) -> NotificationService:
    return SERVICES.get(name)

def notify_new_offers(session: Session, market_name: str, offers: List[Dict[str, Any]]):
    """
    Trigger notifications across all active notification services in the database.
    """
    if not offers:
        return
        
    try:
        stmt = select(NotificationConfig).where(NotificationConfig.enabled == True)
        configs = session.exec(stmt).all()
        
        for config in configs:
            service = get_service(config.service_name)
            if not service:
                print(f"Notification service {config.service_name} registered in DB but not implemented in app")
                continue
                
            settings = config.settings
            if not settings:
                continue
                
            print(f"Sending deal digest to {config.service_name}...")
            success = service.send_digest(settings, market_name, offers)
            if success:
                print(f"Digest successfully sent via {config.service_name}")
            else:
                print(f"Failed to send digest via {config.service_name}")
    except Exception as e:
        print(f"Error executing notifications: {e}")
