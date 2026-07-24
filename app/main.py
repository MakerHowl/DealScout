import asyncio
import uuid
from fastapi import FastAPI, Request, Response, Form, Cookie, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
from typing import Optional
from datetime import datetime, timedelta

from app.database import (
    init_db, get_session, Market, Offer, FavoriteProduct, UserMarketFavorite,
    NotificationConfig, get_notification_config, get_setting, set_setting, User
)
from app.auth import (
    fastapi_users, auth_backend, current_optional_user, current_active_user,
    get_user_manager, UserManager, UserCreate, UserRead
)
from app.scraper import update_market_offers_in_db, PROVIDERS
from app.scheduler import start_scheduler

app = FastAPI(title="Supermarket Offers Search")

# Mount static files and setup templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# PWA Endpoints
@app.get("/manifest.json", include_in_schema=False)
async def get_manifest():
    return FileResponse("app/static/manifest.json", media_type="application/json")

@app.get("/sw.js", include_in_schema=False)
async def get_sw():
    return FileResponse(
        "app/static/js/sw.js", 
        media_type="application/javascript", 
        headers={"Service-Worker-Allowed": "/"}
    )


@app.on_event("startup")
def on_startup():
    init_db()
    asyncio.create_task(start_scheduler())

def require_user(user: Optional[User], request: Request):
    if not user:
        if request.headers.get("HX-Request") == "true":
            return Response(status_code=401, headers={"HX-Redirect": "/login"})
        return RedirectResponse(url="/login", status_code=303)
    return None

def require_admin(user: Optional[User], request: Request):
    redirect = require_user(user, request)
    if redirect:
        return redirect
    if not user.is_superuser:
        if request.headers.get("HX-Request") == "true":
            return Response(status_code=403, headers={"HX-Redirect": "/"})
        return RedirectResponse(url="/", status_code=303)
    return None

# Include standard fastapi-users routers for REST API access if needed
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)

# Authentication HTML View Routes
@app.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    user: Optional[User] = Depends(current_optional_user)
):
    if user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"user": user, "active_page": "login"}
    )

@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    user_manager: UserManager = Depends(get_user_manager),
    strategy = Depends(auth_backend.get_strategy)
):
    credentials = OAuth2PasswordRequestForm(username=username.strip(), password=password)
    user = await user_manager.authenticate(credentials)
    if user is None or not user.is_active:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Ungültige E-Mail-Adresse oder Passwort.", "email": username, "active_page": "login"},
            status_code=400
        )
    
    token = await strategy.write_token(user)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="dealscout_auth", value=token, max_age=3600*24*7, httponly=True, samesite="lax")
    return response

@app.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    user: Optional[User] = Depends(current_optional_user)
):
    if user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"user": user, "active_page": "register"}
    )

@app.post("/register")
async def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    user_manager: UserManager = Depends(get_user_manager),
    strategy = Depends(auth_backend.get_strategy)
):
    try:
        user_create = UserCreate(email=email.strip(), password=password)
        user = await user_manager.create(user_create, safe=True, request=request)
    except Exception as e:
        err_msg = str(e)
        if "REGISTER_USER_ALREADY_EXISTS" in err_msg:
            err_msg = "Eine Registrierung mit dieser E-Mail-Adresse ist bereits vorhanden."
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": f"Registrierung fehlgeschlagen: {err_msg}", "email": email, "active_page": "register"},
            status_code=400
        )
    
    token = await strategy.write_token(user)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="dealscout_auth", value=token, max_age=3600*24*7, httponly=True, samesite="lax")
    return response

@app.get("/logout")
@app.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("dealscout_auth")
    return response

# Main App Routes (Strictly Protected)
@app.get("/", response_class=HTMLResponse)
async def get_index(
    request: Request,
    selected_market_id: Optional[str] = Cookie(default=None),
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

    market = None
    offers_count = 0
    
    if selected_market_id:
        market = db.get(Market, selected_market_id)
        if market:
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
            "active_page": "search",
            "user": user
        }
    )

@app.get("/search-markets", response_class=HTMLResponse)
async def search_markets(
    request: Request,
    q: str = "",
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

    q_clean = q.strip()
    if not q_clean or len(q_clean) < 2:
        return "<p class='text-red-400 mt-4 text-center'>Bitte geben Sie mindestens 2 Zeichen ein.</p>"
        
    markets = []
    for name, provider in PROVIDERS.items():
        try:
            res = provider["search"](q_clean)
            markets.extend(res)
        except Exception as e:
            print(f"Error searching {name} markets: {e}")
            
    favorited_ids = set()
    if markets and user:
        market_ids = [m["id"] for m in markets]
        stmt = select(UserMarketFavorite.market_id).where(
            UserMarketFavorite.user_id == user.id,
            UserMarketFavorite.market_id.in_(market_ids)
        )
        favorited_ids = set(db.exec(stmt).all())
        
    for m in markets:
        m["is_favorite"] = m["id"] in favorited_ids
        
    return templates.TemplateResponse(
        request=request,
        name="components/market_list.html",
        context={"markets": markets, "user": user}
    )

@app.post("/select-market")
async def select_market(
    request: Request,
    response: Response,
    id: str = Form(...),
    name: str = Form(...),
    street: str = Form(...),
    zip_code: str = Form(...),
    city: str = Form(...),
    url: str = Form(...),
    offers_url: str = Form(...),
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

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
        
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="selected_market_id", value=id, max_age=3600*24*30)
    return response

@app.post("/deselect-market")
async def deselect_market(
    request: Request,
    response: Response,
    user: Optional[User] = Depends(current_optional_user)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

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
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect
        
    market = db.get(Market, id)
    if not market:
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
        db.commit()

    fav = db.exec(select(UserMarketFavorite).where(
        UserMarketFavorite.user_id == user.id,
        UserMarketFavorite.market_id == id
    )).first()

    if fav:
        db.delete(fav)
        is_favorite = False
    else:
        db.add(UserMarketFavorite(user_id=user.id, market_id=id))
        is_favorite = True
    db.commit()

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
            "is_favorite": is_favorite,
            "user": user
        }
    )

@app.get("/favorites-list", response_class=HTMLResponse)
async def get_favorites_list(
    request: Request,
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

    fav_ids = db.exec(select(UserMarketFavorite.market_id).where(UserMarketFavorite.user_id == user.id)).all()
    if not fav_ids:
        favorites = []
    else:
        favorites = db.exec(select(Market).where(Market.id.in_(fav_ids))).all()
        
    return templates.TemplateResponse(
        request=request,
        name="components/favorites_list.html",
        context={"favorites": favorites, "user": user}
    )

@app.get("/search-offers", response_class=HTMLResponse)
async def search_offers(
    request: Request,
    q: str = "",
    selected_market_id: Optional[str] = Cookie(default=None),
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

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
        context={"offers": offers, "query": q, "market": market, "user": user}
    )

@app.post("/refresh-offers", response_class=HTMLResponse)
async def refresh_offers(
    request: Request,
    selected_market_id: Optional[str] = Cookie(default=None),
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

    if not selected_market_id:
        return "<div class='text-red-400 text-center'>Kein Markt ausgewählt.</div>"
        
    success = update_market_offers_in_db(selected_market_id, db)
    market = db.get(Market, selected_market_id)
    
    offers = db.exec(select(Offer).where(Offer.market_id == selected_market_id)).all()
    
    return templates.TemplateResponse(
        request=request,
        name="components/offer_results.html",
        context={"offers": offers, "market": market, "refreshed": success, "user": user}
    )

@app.get("/favorites-offers", response_class=HTMLResponse)
async def get_favorites_offers(
    request: Request,
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

    fav_ids = db.exec(select(UserMarketFavorite.market_id).where(UserMarketFavorite.user_id == user.id)).all()
    if not fav_ids:
        favorites = []
    else:
        favorites = db.exec(select(Market).where(Market.id.in_(fav_ids))).all()
        
    return templates.TemplateResponse(
        request=request,
        name="favorites_offers.html",
        context={"favorites": favorites, "active_page": "fav_offers", "user": user}
    )

@app.post("/refresh-favorite-market-offers/{market_id}", response_class=HTMLResponse)
async def refresh_favorite_market_offers(
    market_id: str,
    request: Request,
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

    success = update_market_offers_in_db(market_id, db)
    market = db.get(Market, market_id)
    if not market:
        return "<p class='text-red-400'>Markt existiert nicht.</p>"
        
    return templates.TemplateResponse(
        request=request,
        name="components/offers_scroll_row.html",
        context={"market": market, "refreshed": success, "user": user}
    )

@app.get("/favorite-products", response_class=HTMLResponse)
async def get_favorite_products_page(
    request: Request,
    user: Optional[User] = Depends(current_optional_user)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        request=request,
        name="favorite_products.html",
        context={"active_page": "fav_products", "user": user}
    )

@app.get("/favorite-products-list", response_class=HTMLResponse)
async def get_favorite_products_list(
    request: Request,
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

    products = db.exec(
        select(FavoriteProduct)
        .where(FavoriteProduct.user_id == user.id)
        .order_by(FavoriteProduct.name)
    ).all()
        
    return templates.TemplateResponse(
        request=request,
        name="components/favorite_products_list.html",
        context={"products": products, "user": user}
    )

@app.post("/add-favorite-product", response_class=HTMLResponse)
async def add_favorite_product(
    request: Request,
    response: Response,
    name: str = Form(...),
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect
        
    name_clean = name.strip()
    if not name_clean:
        return "<span class='text-red-400'>Produktname darf nicht leer sein.</span>"
        
    stmt = select(FavoriteProduct).where(FavoriteProduct.user_id == user.id)
    existing_products = db.exec(stmt).all()
    if any(p.name.lower() == name_clean.lower() for p in existing_products):
        return "<span class='text-amber-400'>Dieses Produkt ist bereits in deiner Liste.</span>"
        
    new_prod = FavoriteProduct(user_id=user.id, name=name_clean)
    db.add(new_prod)
    db.commit()
    
    response.headers["HX-Trigger"] = "update-favorite-products"
    return "<span class='text-green-400'>Erfolgreich hinzugefügt!</span>"

@app.delete("/delete-favorite-product/{product_id}")
async def delete_favorite_product(
    product_id: int,
    request: Request,
    response: Response,
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect
        
    prod = db.exec(select(FavoriteProduct).where(
        FavoriteProduct.id == product_id,
        FavoriteProduct.user_id == user.id
    )).first()
    if prod:
        db.delete(prod)
        db.commit()
        response.headers["HX-Trigger"] = "update-favorite-products"
    return ""

@app.get("/favorite-products-offers", response_class=HTMLResponse)
async def get_favorite_products_offers(
    request: Request,
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

    fav_ids = db.exec(select(UserMarketFavorite.market_id).where(UserMarketFavorite.user_id == user.id)).all()
    favorite_markets = db.exec(select(Market).where(Market.id.in_(fav_ids))).all() if fav_ids else []
    
    products = db.exec(select(FavoriteProduct).where(FavoriteProduct.user_id == user.id).order_by(FavoriteProduct.name)).all()
    
    offers_by_product = {}
    
    if fav_ids and products:
        offers = db.exec(select(Offer).where(Offer.market_id.in_(fav_ids))).all()
        
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
            "offers_by_product": offers_by_product,
            "user": user
        }
    )

@app.get("/settings", response_class=HTMLResponse)
async def get_settings_page(
    request: Request,
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

    from croniter import croniter
    pushover_cfg = get_notification_config(db, user.id, "pushover")
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
            "active_page": "settings",
            "user": user
        }
    )

@app.post("/settings/cron", response_class=HTMLResponse)
async def save_cron_settings(
    request: Request,
    cron: str = Form(""),
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

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
    request: Request,
    user_key: str = Form(""),
    api_token: str = Form(""),
    enabled: bool = Form(False),
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

    config = get_notification_config(db, user.id, "pushover")
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
    request: Request,
    user_key: str = Form(""),
    api_token: str = Form(""),
    user: Optional[User] = Depends(current_optional_user)
):
    redirect = require_user(user, request)
    if redirect:
        return redirect

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

# Admin User Management Routes
@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(
    request: Request,
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_admin(user, request)
    if redirect:
        return redirect

    users = db.exec(select(User).order_by(User.email)).unique().all()
    return templates.TemplateResponse(
        request=request,
        name="admin_users.html",
        context={
            "users": users,
            "active_page": "admin_users",
            "user": user
        }
    )

@app.delete("/admin/users/{user_id_to_delete}", response_class=HTMLResponse)
async def delete_user(
    user_id_to_delete: str,
    request: Request,
    user: Optional[User] = Depends(current_optional_user),
    db: Session = Depends(get_session)
):
    redirect = require_admin(user, request)
    if redirect:
        return redirect

    if str(user.id) == str(user_id_to_delete):
        users = db.exec(select(User).order_by(User.email)).unique().all()
        return templates.TemplateResponse(
            request=request,
            name="components/admin_users_list.html",
            context={"users": users, "user": user}
        )

    try:
        target_uuid = uuid.UUID(user_id_to_delete)
    except ValueError:
        users = db.exec(select(User).order_by(User.email)).unique().all()
        return templates.TemplateResponse(
            request=request,
            name="components/admin_users_list.html",
            context={"users": users, "user": user}
        )

    # Delete related data first
    # 1. Favorite Products
    prods = db.exec(select(FavoriteProduct).where(FavoriteProduct.user_id == target_uuid)).all()
    for p in prods:
        db.delete(p)

    # 2. User Market Favorites
    market_favs = db.exec(select(UserMarketFavorite).where(UserMarketFavorite.user_id == target_uuid)).all()
    for mf in market_favs:
        db.delete(mf)

    # 3. Notification Configs
    notifs = db.exec(select(NotificationConfig).where(NotificationConfig.user_id == target_uuid)).all()
    for n in notifs:
        db.delete(n)

    # 4. User
    target_user = db.get(User, target_uuid)
    if target_user:
        db.delete(target_user)
        db.commit()

    users = db.exec(select(User).order_by(User.email)).unique().all()
    return templates.TemplateResponse(
        request=request,
        name="components/admin_users_list.html",
        context={"users": users, "user": user}
    )
