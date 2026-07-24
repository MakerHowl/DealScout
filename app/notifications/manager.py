import uuid
from typing import Dict, List, Any, Set
from sqlmodel import Session, select
from app.database import NotificationConfig, UserMarketFavorite, FavoriteProduct
from app.notifications.base import NotificationService
from app.notifications.pushover import PushoverService

# Registry mapping service identifier names to their implementations
SERVICES: Dict[str, NotificationService] = {
    "pushover": PushoverService()
}

def get_service(name: str) -> NotificationService:
    return SERVICES.get(name)

def notify_new_offers(session: Session, market_id: str, market_name: str, offers_data: List[Dict[str, Any]], old_offer_ids: Set[str]):
    """
    Trigger user-specific notifications across all active users who favorited this market.
    """
    if not offers_data:
        return
        
    try:
        # Find all users who have favorited this market
        fav_users_stmt = select(UserMarketFavorite.user_id).where(UserMarketFavorite.market_id == market_id)
        user_ids = set(session.exec(fav_users_stmt).all())
        if not user_ids:
            return
            
        new_offers = [o for o in offers_data if o["id"] not in old_offer_ids]
        if not new_offers:
            return

        for user_id in user_ids:
            # Check if this user has enabled Pushover notifications
            config = session.get(NotificationConfig, (user_id, "pushover"))
            if not config or not config.enabled:
                continue

            settings = config.settings
            if not settings:
                continue

            # Check if user has favorite products to filter against
            user_products = session.exec(select(FavoriteProduct).where(FavoriteProduct.user_id == user_id)).all()
            if user_products:
                matching_offers = []
                for o_data in new_offers:
                    title_lower = o_data["title"].lower()
                    desc_lower = (o_data.get("description") or "").lower()
                    for prod in user_products:
                        prod_lower = prod.name.lower()
                        if prod_lower in title_lower or prod_lower in desc_lower:
                            matching_offers.append(o_data)
                            break
                digest_offers = matching_offers
            else:
                digest_offers = new_offers

            if not digest_offers:
                continue

            service = get_service("pushover")
            if service:
                print(f"Sending deal digest to user {user_id} via pushover...")
                service.send_digest(settings, market_name, digest_offers)

    except Exception as e:
        print(f"Error executing notifications: {e}")
