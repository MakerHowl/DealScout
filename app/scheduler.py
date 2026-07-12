import asyncio
from datetime import datetime, timezone
from croniter import croniter
from sqlmodel import Session, select
from app.database import engine, Market, AppSetting, get_setting, set_setting

def run_automatic_refresh():
    """
    Perform a stateful cron-based check and run automatic offer updates for favorite markets.
    """
    with Session(engine) as session:
        # 1. Retrieve the configured cron expression
        cron_expr = get_setting(session, "refresh_cron", "0 0 * * *").strip()
        
        # Validate expression, fallback if malformed
        if not croniter.is_valid(cron_expr):
            print(f"Warning: Invalid cron expression '{cron_expr}' detected. Falling back to daily at midnight ('0 0 * * *').")
            cron_expr = "0 0 * * *"
            
        # 2. Retrieve the last execution timestamp
        last_refresh_str = get_setting(session, "last_automatic_refresh", "")
        last_refresh = None
        if last_refresh_str:
            try:
                last_refresh = datetime.fromisoformat(last_refresh_str)
            except Exception:
                pass
                
        now = datetime.utcnow()
        should_run = False
        
        if not last_refresh:
            # First execution: run immediately
            print("No previous automatic refresh found. Triggering first run...")
            should_run = True
        else:
            try:
                # Calculate the next scheduled run time after last_refresh
                cron = croniter(cron_expr, last_refresh)
                next_scheduled_run = cron.get_next(datetime)
                
                # Check if we have passed the scheduled run time
                if now >= next_scheduled_run:
                    should_run = True
            except Exception as cron_err:
                print(f"Error computing next scheduled run: {cron_err}")
                # Fallback to run if last_refresh is older than 24 hours
                if (now - last_refresh).total_seconds() > 86400:
                    should_run = True
                    
        if should_run:
            print(f"Cron scheduler trigger: Starting automatic refresh (cron: '{cron_expr}')...")
            
            # Retrieve favorite markets
            favorite_markets = session.exec(select(Market).where(Market.is_favorite == True)).all()
            if favorite_markets:
                from app.scraper import update_market_offers_in_db
                for market in favorite_markets:
                    print(f"Auto-refreshing offers for favorite market: {market.name}...")
                    try:
                        update_market_offers_in_db(market.id, session)
                    except Exception as scrape_err:
                        print(f"Failed to auto-refresh market {market.name} ({market.id}): {scrape_err}")
            else:
                print("No favorite markets defined. Skipping scraper runs.")
                
            # Update last automatic refresh timestamp
            set_setting(session, "last_automatic_refresh", now.isoformat())
            print("Automatic refresh cycle completed.")

async def start_scheduler():
    """
    Background asyncio loop to run the scheduler check every 60 seconds.
    """
    print("Background cron scheduler loop started.")
    # Wait a few seconds after startup before checking
    await asyncio.sleep(5)
    while True:
        try:
            # Run the synchronous refresh check
            run_automatic_refresh()
        except Exception as loop_err:
            print(f"Error in scheduler check loop: {loop_err}")
        # Check again in 60 seconds
        await asyncio.sleep(60)
