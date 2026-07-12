from fastapi import FastAPI, Request, Response, Form, Cookie, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from typing import Optional
from datetime import datetime, timedelta

from app.database import init_db, get_session, Market, Offer
from app.scraper import search_edeka_markets, update_market_offers_in_db

app = FastAPI(title="Supermarket Offers Search")

# Mount static files and setup templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.on_event("startup")
def on_startup():
    init_db()

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
