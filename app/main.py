import asyncio
from fastapi import FastAPI, Request, Response, Form, Cookie, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from typing import Optional
from datetime import datetime, timedelta

from app.database import init_db, get_session, Market, Offer, FavoriteProduct, NotificationConfig, get_notification_config, get_setting, set_setting
from app.scraper import search_edeka_markets, update_market_offers_in_db
from app.scheduler import start_scheduler

app = FastAPI(title="Supermarket Offers Search")

# Mount static files and setup templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.on_event("startup")
def on_startup():
    init_db()
    asyncio.create_task(start_scheduler())

@app.get("/", response_class=HTMLResponse)
async def get_index(
    request: Request,
    selected_market_id: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_session)
):
    market = None
    offers_count = 0
    
    if selected_market_id:
        market = db.get(Market, selected_market_id)
        if market:
            # Check if we need to auto-scrape (e.g. if last_scraped is older than 24 hours or None)
            needs_scrape = (
                not market.last_scraped or 
                datetime.utcnow() - market.last_scraped > timedelta(hours=24)
            )
            if needs_scrape:
                print(f"Auto-scraping offers for market {market.name}...")
                update_market_offers_in_db(market.id, db)
                db.refresh(market)
                
            offers_count = len(market.offers)
            
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "market": market,
            "offers_count": offers_count,
            "active_page": "search"
        }
    )

@app.get("/search-markets", response_class=HTMLResponse)
async def search_markets(
    request: Request,
    q: str = "",
    db: Session = Depends(get_session)
):
    if not q or len(q.strip()) < 2:
        return "<p class='text-red-400 mt-4 text-center'>Bitte geben Sie mindestens 2 Zeichen ein.</p>"
        
    markets = search_edeka_markets(q.strip())
    
    # Check database to see which markets are already favorited
    favorited_ids = set()
    if markets:
        market_ids = [m["id"] for m in markets]
        stmt = select(Market.id).where(Market.id.in_(market_ids)).where(Market.is_favorite == True)
        favorited_ids = set(db.exec(stmt).all())
        
    for m in markets:
        m["is_favorite"] = m["id"] in favorited_ids
        
    return templates.TemplateResponse(
        request=request,
        name="components/market_list.html",
        context={"markets": markets}
    )

@app.post("/select-market")
async def select_market(
    response: Response,
    id: str = Form(...),
    name: str = Form(...),
    street: str = Form(...),
    zip_code: str = Form(...),
    city: str = Form(...),
    url: str = Form(...),
    offers_url: str = Form(...),
    db: Session = Depends(get_session)
):
    # 1. Check if market exists in DB, otherwise create it
    market = db.get(Market, id)
    if not market:
        market = Market(
            id=id,
            name=name,
            street=street,
            zip_code=zip_code,
            city=city,
            url=url,
            offers_url=offers_url
        )
        db.add(market)
        db.commit()
        db.refresh(market)
        
    # 2. Set the cookie for the selected market
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="selected_market_id", value=id, max_age=3600*24*30) # 30 days
    return response

@app.post("/deselect-market")
async def deselect_market(response: Response):
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="selected_market_id")
    return response

@app.post("/toggle-favorite", response_class=HTMLResponse)
async def toggle_favorite(
    request: Request,
    response: Response,
    id: str = Form(...),
    name: Optional[str] = Form(None),
    street: Optional[str] = Form(None),
    zip_code: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    offers_url: Optional[str] = Form(None),
    db: Session = Depends(get_session)
):
    market = db.get(Market, id)
    if not market:
        # Create the market if it doesn't exist
        market = Market(
            id=id,
            name=name or "",
            street=street or "",
            zip_code=zip_code or "",
            city=city or "",
            url=url or "",
            offers_url=offers_url or ""
        )
        db.add(market)
        
    market.is_favorite = not market.is_favorite
    db.commit()
    db.refresh(market)
    
    # Trigger HTMX event to update the favorites list on the page
    response.headers["HX-Trigger"] = "update-favorites"
    
    return templates.TemplateResponse(
        request=request,
        name="components/favorite_button.html",
        context={
            "id": market.id,
            "name": market.name,
            "street": market.street,
            "zip_code": market.zip_code,
            "city": market.city,
            "url": market.url,
            "offers_url": market.offers_url,
            "is_favorite": market.is_favorite
        }
    )

@app.get("/favorites-list", response_class=HTMLResponse)
async def get_favorites_list(
    request: Request,
    db: Session = Depends(get_session)
):
    stmt = select(Market).where(Market.is_favorite == True)
    favorites = db.exec(stmt).all()
    return templates.TemplateResponse(
        request=request,
        name="components/favorites_list.html",
        context={"favorites": favorites}
    )

@app.get("/search-offers", response_class=HTMLResponse)
async def search_offers(
    request: Request,
    q: str = "",
    selected_market_id: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_session)
):
    if not selected_market_id:
        return "<p class='text-red-400 text-center'>Kein Markt ausgewählt.</p>"
        
    market = db.get(Market, selected_market_id)
    if not market:
        return "<p class='text-red-400 text-center'>Markt existiert nicht in Datenbank.</p>"
        
    query = select(Offer).where(Offer.market_id == selected_market_id)
    if q and len(q.strip()) > 0:
        query = query.where(Offer.title.like(f"%{q.strip()}%") | Offer.description.like(f"%{q.strip()}%"))
        
    offers = db.exec(query).all()
    
    return templates.TemplateResponse(
        request=request,
        name="components/offer_results.html",
        context={"offers": offers, "query": q, "market": market}
    )

@app.post("/refresh-offers", response_class=HTMLResponse)
async def refresh_offers(
    request: Request,
    selected_market_id: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_session)
):
    if not selected_market_id:
        return "<div class='text-red-400 text-center'>Kein Markt ausgewählt.</div>"
        
    success = update_market_offers_in_db(selected_market_id, db)
    market = db.get(Market, selected_market_id)
    
    # Reload all offers
    offers = db.exec(select(Offer).where(Offer.market_id == selected_market_id)).all()
    
    return templates.TemplateResponse(
        request=request,
        name="components/offer_results.html",
        context={"offers": offers, "market": market, "refreshed": success}
    )

@app.get("/favorites-offers", response_class=HTMLResponse)
async def get_favorites_offers(
    request: Request,
    db: Session = Depends(get_session)
):
    stmt = select(Market).where(Market.is_favorite == True)
    favorites = db.exec(stmt).all()
    return templates.TemplateResponse(
        request=request,
        name="favorites_offers.html",
        context={"favorites": favorites, "active_page": "fav_offers"}
    )

@app.post("/refresh-favorite-market-offers/{market_id}", response_class=HTMLResponse)
async def refresh_favorite_market_offers(
    market_id: str,
    request: Request,
    db: Session = Depends(get_session)
):
    success = update_market_offers_in_db(market_id, db)
    market = db.get(Market, market_id)
    if not market:
        return "<p class='text-red-400'>Markt existiert nicht.</p>"
        
    return templates.TemplateResponse(
        request=request,
        name="components/offers_scroll_row.html",
        context={"market": market, "refreshed": success}
    )

@app.get("/favorite-products", response_class=HTMLResponse)
async def get_favorite_products_page(
    request: Request,
    db: Session = Depends(get_session)
):
    return templates.TemplateResponse(
        request=request,
        name="favorite_products.html",
        context={"active_page": "fav_products"}
    )

@app.get("/favorite-products-list", response_class=HTMLResponse)
async def get_favorite_products_list(
    request: Request,
    db: Session = Depends(get_session)
):
    products = db.exec(select(FavoriteProduct).order_by(FavoriteProduct.name)).all()
    return templates.TemplateResponse(
        request=request,
        name="components/favorite_products_list.html",
        context={"products": products}
    )

@app.post("/add-favorite-product", response_class=HTMLResponse)
async def add_favorite_product(
    response: Response,
    name: str = Form(...),
    db: Session = Depends(get_session)
):
    name_clean = name.strip()
    if not name_clean:
        return "<span class='text-red-400'>Produktname darf nicht leer sein.</span>"
        
    stmt = select(FavoriteProduct)
    existing_products = db.exec(stmt).all()
    if any(p.name.lower() == name_clean.lower() for p in existing_products):
        return "<span class='text-amber-400'>Dieses Produkt ist bereits in deiner Liste.</span>"
        
    new_prod = FavoriteProduct(name=name_clean)
    db.add(new_prod)
    db.commit()
    
    response.headers["HX-Trigger"] = "update-favorite-products"
    return "<span class='text-green-400'>Erfolgreich hinzugefügt!</span>"

@app.delete("/delete-favorite-product/{product_id}")
async def delete_favorite_product(
    product_id: int,
    response: Response,
    db: Session = Depends(get_session)
):
    prod = db.get(FavoriteProduct, product_id)
    if prod:
        db.delete(prod)
        db.commit()
        response.headers["HX-Trigger"] = "update-favorite-products"
    return ""

@app.get("/favorite-products-offers", response_class=HTMLResponse)
async def get_favorite_products_offers(
    request: Request,
    db: Session = Depends(get_session)
):
    favorite_markets = db.exec(select(Market).where(Market.is_favorite == True)).all()
    fav_market_ids = [m.id for m in favorite_markets]
    
    products = db.exec(select(FavoriteProduct).order_by(FavoriteProduct.name)).all()
    
    offers_by_product = {}
    
    if fav_market_ids and products:
        offers = db.exec(select(Offer).where(Offer.market_id.in_(fav_market_ids))).all()
        
        for prod in products:
            prod_name_lower = prod.name.lower()
            matching_offers = []
            for offer in offers:
                title_match = prod_name_lower in offer.title.lower()
                desc_match = offer.description and prod_name_lower in offer.description.lower()
                if title_match or desc_match:
                    matching_offers.append(offer)
            if matching_offers:
                offers_by_product[prod.name] = matching_offers
                
    return templates.TemplateResponse(
        request=request,
        name="components/favorite_products_offers.html",
        context={
            "favorite_markets": favorite_markets,
            "products": products,
            "offers_by_product": offers_by_product
        }
    )

@app.get("/settings", response_class=HTMLResponse)
async def get_settings_page(
    request: Request,
    db: Session = Depends(get_session)
):
    from croniter import croniter
    pushover_cfg = get_notification_config(db, "pushover")
    cron_expr = get_setting(db, "refresh_cron", "0 0 * * *")
    
    next_run_str = "Ungültig oder nicht gesetzt"
    if croniter.is_valid(cron_expr):
        try:
            cron = croniter(cron_expr, datetime.utcnow())
            next_run = cron.get_next(datetime)
            next_run_str = next_run.strftime("%d.%m.%Y um %H:%M UTC")
        except Exception:
            pass
            
    last_refresh_raw = get_setting(db, "last_automatic_refresh", "")
    last_refresh_str = "Bisher noch nicht ausgeführt"
    if last_refresh_raw:
        try:
            last_refresh_dt = datetime.fromisoformat(last_refresh_raw)
            last_refresh_str = last_refresh_dt.strftime("%d.%m.%Y um %H:%M UTC")
        except Exception:
            pass

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "pushover": pushover_cfg,
            "cron_expr": cron_expr,
            "next_run_str": next_run_str,
            "last_refresh_str": last_refresh_str,
            "active_page": "settings"
        }
    )

@app.post("/settings/cron", response_class=HTMLResponse)
async def save_cron_settings(
    cron: str = Form(""),
    db: Session = Depends(get_session)
):
    from croniter import croniter
    cron_clean = cron.strip()
    
    if not croniter.is_valid(cron_clean):
        return "<div class='alert alert-danger' style='background: rgba(239, 68, 68, 0.15); border-color: rgba(239, 68, 68, 0.3); color: #F87171; padding: 1rem 1.5rem; border-radius: 12px; margin-bottom: 1rem;'>Ungültiger Cron-Ausdruck. Bitte verwende das Standard-Format (z.B. '0 0 * * *').</div>"
        
    set_setting(db, "refresh_cron", cron_clean)
    
    next_run_str = "Ungültig"
    try:
        cron_obj = croniter(cron_clean, datetime.utcnow())
        next_run = cron_obj.get_next(datetime)
        next_run_str = next_run.strftime("%d.%m.%Y um %H:%M UTC")
    except Exception:
        pass
        
    success_msg = "<div class='alert alert-success fade-in'>Cron-Zeitplan erfolgreich gespeichert!</div>"
    oob_update = f'<strong id="next-run-time" style="color: var(--primary);" hx-swap-oob="true">{next_run_str}</strong>'
    return success_msg + oob_update

@app.post("/settings/pushover", response_class=HTMLResponse)
async def save_pushover_settings(
    user_key: str = Form(""),
    api_token: str = Form(""),
    enabled: bool = Form(False),
    db: Session = Depends(get_session)
):
    config = get_notification_config(db, "pushover")
    config.enabled = enabled
    config.settings = {
        "user_key": user_key.strip(),
        "api_token": api_token.strip()
    }
    db.add(config)
    db.commit()
    return "<div class='alert alert-success fade-in'>Pushover-Einstellungen erfolgreich gespeichert!</div>"

@app.post("/settings/pushover/test", response_class=HTMLResponse)
async def test_pushover_settings(
    user_key: str = Form(""),
    api_token: str = Form("")
):
    from app.notifications.manager import get_service
    pushover_service = get_service("pushover")
    
    if not pushover_service:
        return "<div class='alert alert-danger' style='background: rgba(239, 68, 68, 0.15); border-color: rgba(239, 68, 68, 0.3); color: #F87171; padding: 1rem 1.5rem; border-radius: 12px; margin-bottom: 1rem;'>Fehler: Pushover-Dienst ist nicht registriert.</div>"
        
    settings = {
        "user_key": user_key.strip(),
        "api_token": api_token.strip()
    }
    success = pushover_service.send_test(settings)
    if success:
        return "<div class='alert alert-success fade-in'>Test-Benachrichtigung erfolgreich gesendet! Bitte überprüfe dein Gerät.</div>"
    else:
        return "<div class='alert alert-danger' style='background: rgba(239, 68, 68, 0.15); border-color: rgba(239, 68, 68, 0.3); color: #F87171; padding: 1rem 1.5rem; border-radius: 12px; margin-bottom: 1rem;'>Senden der Test-Benachrichtigung fehlgeschlagen. Bitte überprüfe User Key und API Token.</div>"
