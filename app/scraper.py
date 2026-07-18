from curl_cffi import requests
import urllib.parse
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select
from app.database import Market, Offer


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_lidl_validity(p: Dict[str, Any]) -> tuple:
    valid_from = None
    valid_until = None
    
    # 1. Try storeStartDate/storeEndDate (timestamps)
    start_ts = p.get("storeStartDate")
    end_ts = p.get("storeEndDate")
    if start_ts and isinstance(start_ts, (int, float)):
        try:
            valid_from = datetime.fromtimestamp(start_ts).strftime("%d.%m.")
        except Exception:
            pass
    if end_ts and isinstance(end_ts, (int, float)):
        try:
            valid_until = datetime.fromtimestamp(end_ts).strftime("%d.%m.")
        except Exception:
            pass
            
    # 2. Try campaign info (ISO strings) if timestamps not present
    if not valid_from or not valid_until:
        campaign_info = p.get("campaign")
        if isinstance(campaign_info, dict):
            start_raw = campaign_info.get("startDate")
            end_raw = campaign_info.get("endDate")
            if start_raw and not valid_from:
                try:
                    valid_from = datetime.fromisoformat(str(start_raw).replace('Z', '+00:00')).strftime("%d.%m.")
                except Exception:
                    valid_from = str(start_raw)[:10]
            if end_raw and not valid_until:
                try:
                    valid_until = datetime.fromisoformat(str(end_raw).replace('Z', '+00:00')).strftime("%d.%m.")
                except Exception:
                    valid_until = str(end_raw)[:10]
                    
    return valid_from, valid_until

def search_edeka_markets(query: str) -> List[Dict[str, Any]]:
    """
    Search Edeka markets by zip code or city name.
    """
    url = "https://www.edeka.de/api/marketsearch/markets"
    params = {"searchstring": query}
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
        "Referer": "https://www.edeka.de/marktsuche.jsp",
        "Connection": "keep-alive"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, impersonate="chrome110", timeout=15, verify=False)
        if response.status_code != 200:
            print(f"Error searching markets: HTTP {response.status_code}")
            return []
            
        data = response.json()
        raw_markets = data.get("markets", [])
        
        markets = []
        for m in raw_markets:
            market_id = str(m.get("id"))
            name = m.get("name", "")
            
            # Extract address
            contact = m.get("contact", {})
            address = contact.get("address", {})
            street = address.get("street", "")
            city_info = address.get("city", {})
            zip_code = city_info.get("zipCode", "")
            city = city_info.get("name", "")
            
            # Construct URLs
            url_path = m.get("url", "")
            if not url_path:
                continue
                
            # Replace index.jsp with angebote.jsp to get the offers URL
            offers_url = url_path.replace("index.jsp", "angebote.jsp")
            
            markets.append({
                "id": market_id,
                "name": name,
                "street": street,
                "zip_code": zip_code,
                "city": city,
                "url": url_path,
                "offers_url": offers_url
            })
        return markets
    except Exception as e:
        print(f"Error searching markets: {e}")
        return []

def scrape_edeka_offers(offers_url: str, market_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Download and parse the offers page of an Edeka market.
    """
    # Fallback for custom merchant domains (e.g. www.kochmarkt.de)
    # If the URL is not a standard Edeka URL and we have the market_id, resolve the official Edeka offerUrl
    if market_id and ("edeka.de" not in offers_url or not offers_url.endswith("angebote.jsp")):
        print(f"Custom offers URL detected: {offers_url}. Resolving via Edeka market-gateway for market {market_id}...")
        gateway_url = f"https://www.edeka.de/api/market-gateway?marketId={market_id}"
        gateway_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.edeka.de/marktsuche.jsp",
            "Connection": "keep-alive"
        }
        try:
            r = requests.get(gateway_url, headers=gateway_headers, impersonate="chrome110", timeout=15, verify=False)
            if r.status_code == 200:
                data = r.json()
                resolved_url = data.get("offerUrl")
                if resolved_url:
                    print(f"Resolved offers URL to: {resolved_url}")
                    offers_url = resolved_url
        except Exception as e:
            print(f"Error resolving offers URL via gateway: {e}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
        "Referer": "https://www.edeka.de/",
        "Connection": "keep-alive"
    }
    try:
        response = requests.get(offers_url, headers=headers, impersonate="chrome110", timeout=20, verify=False)
        if response.status_code != 200:
            print(f"Error scraping offers: HTTP {response.status_code}")
            return []
            
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        dialogs = soup.find_all('dialog')
            
        offers = []
        seen_ids = set()
        for dialog in dialogs:
            dialog_id = dialog.get('id', '')
            if not dialog_id.startswith('dialog-angebot-'):
                continue
            
            offer_id = dialog_id.replace('dialog-angebot-', '')
            if offer_id in seen_ids:
                continue
            seen_ids.add(offer_id)
            
            # 1. Title
            title = ""
            title_el = dialog.find('h3', class_='font-display')
            if title_el:
                title = clean_text(title_el.text)
                title = re.sub(r'^Angebot:\s*', '', title).strip()
            if not title:
                # Fallback to any h3 or h2
                title_el = dialog.find(['h3', 'h2'])
                if title_el:
                    title = clean_text(title_el.text)
                    title = re.sub(r'^Angebot:\s*', '', title).strip()
            
            if not title:
                continue # Ignore empty offers
                
            # 2. Price
            price = None
            app_price = None
            discount_percentage = None
            
            # Scan all sr-only text blocks inside this dialog
            sr_onlys = dialog.find_all(class_='sr-only')
            for sr in sr_onlys:
                sr_text = clean_text(sr.text)
                
                price_val_match = re.search(r'(?:von|Preis)\s*([\d\.,]+)', sr_text)
                if price_val_match:
                    val = price_val_match.group(1).replace(',', '.')
                    try:
                        val_float = float(val)
                    except ValueError:
                        val_float = None
                        
                    if val_float is not None:
                        if "festpreis" in sr_text.lower():
                            price = val_float
                        elif "app-preis" in sr_text.lower():
                            app_price = val_float
                        elif "rabattierter" in sr_text.lower():
                            price = val_float
                            
                percent_match = re.search(r'-(\d+)\s*%', sr_text)
                if percent_match:
                    discount_percentage = int(percent_match.group(1))
            
            # Fallback regular price search if not found in sr-only
            if price is None:
                price_match = re.search(r'(\d+,\d{2})\s*(?:€|EUR)?', clean_text(dialog.text))
                if price_match:
                    price = float(price_match.group(1).replace(',', '.'))
            
            # 3. Image
            img_el = dialog.find('img')
            image_url = img_el.get('src', '') if img_el else ''
            if image_url and image_url.startswith('/'):
                image_url = "https://www.edeka.de" + image_url
            
            # 4. Description
            # Try finding line-cl or line-clamp classes, or any p tag
            desc_el = dialog.find('p', class_=re.compile(r'line-cl'))
            if not desc_el:
                desc_el = dialog.find('p')
            description = clean_text(desc_el.text) if desc_el else ""
            
            # 5. Base price / quantity unit
            base_el = dialog.find('span', class_='text-grey')
            base_price = clean_text(base_el.text) if base_el else ""
            
            # 6. Badge (e.g. Superknüller)
            badge = ""
            badge_el = dialog.find('span', class_=re.compile(r'bg-red'))
            if badge_el:
                badge = clean_text(badge_el.text)
                badge = re.sub(r'^Tag:\s*', '', badge).strip()
                
            # 7. Validity
            valid_from = None
            valid_until = None
            valid_match = re.search(r'Gültig\s+(?:von|ab)\s+((?:[a-zA-ZäöüÄÖÜ]{2}\.?\s*)?\d{1,2}\.\d{1,2}\.?(?:\d{2,4})?)(?:\s+bis\s+((?:[a-zA-ZäöüÄÖÜ]{2}\.?\s*)?\d{1,2}\.\d{1,2}\.?(?:\d{2,4})?))?', clean_text(dialog.text), re.IGNORECASE)
            if valid_match:
                valid_from = valid_match.group(1).strip()
                if valid_match.group(2):
                    valid_until = valid_match.group(2).strip()
                
            offers.append({
                "id": offer_id,
                "title": title,
                "price": price,
                "app_price": app_price,
                "discount_percentage": discount_percentage,
                "image_url": image_url,
                "description": description,
                "base_price": base_price,
                "badge": badge,
                "valid_from": valid_from,
                "valid_until": valid_until
            })
            
        return offers
    except Exception as e:
        print(f"Error scraping offers: {e}")
        return []

def search_lidl_markets(query: str) -> List[Dict[str, Any]]:
    """
    Search Lidl markets (dynamically generated based on search query).
    """
    query_clean = query.strip()
    if not query_clean or len(query_clean) < 2:
        return []
        
    # If query is a postal code
    if query_clean.isdigit():
        return [{
            "id": f"lidl-{query_clean}",
            "name": f"Lidl Filiale",
            "street": "Hauptstraße 1",
            "zip_code": query_clean,
            "city": "Gesuchter Ort",
            "url": "https://www.lidl.de",
            "offers_url": "https://www.lidl.de/angebote"
        }]
    
    # If query is a city name
    return [{
        "id": f"lidl-{query_clean.lower().replace(' ', '-')}",
        "name": f"Lidl Filiale {query_clean.title()}",
        "street": "Hauptstraße 1",
        "zip_code": "00000",
        "city": query_clean.title(),
        "url": "https://www.lidl.de",
        "offers_url": "https://www.lidl.de/angebote"
    }]

def scrape_lidl_offers(offers_url: str, market_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Scrape Lidl offers by crawling the homepage for campaigns and parsing Nuxt 3 payloads as well as inline data-grid-data attributes.
    """
    import html
    base_url = "https://www.lidl.de/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
        "Connection": "keep-alive"
    }
    
    try:
        response = requests.get(base_url, headers=headers, impersonate="chrome110", timeout=20, verify=False)
        if response.status_code != 200:
            return []
    except Exception as e:
        print(f"Error fetching Lidl homepage: {e}")
        return []
        
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Extract campaign links matching /a[0-9]+
    campaign_urls = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        full_url = urllib.parse.urljoin(base_url, href)
        path = urllib.parse.urlparse(full_url).path
        if "/c/" in path and re.search(r'/a\d+', path):
            if any(x in full_url for x in ["impressum", "agb", "datenschutz", "cookies", "widerrufsrecht", "newsletter", "lidl-connect", "reisen", "fotos", "mobil"]):
                continue
            if full_url not in campaign_urls:
                campaign_urls.append(full_url)
                
    max_campaigns = 8
    offers = []
    seen_ids = set()
    
    for url in campaign_urls[:max_campaigns]:
        try:
            r = requests.get(url, headers=headers, impersonate="chrome110", timeout=20, verify=False)
            if r.status_code != 200:
                continue
                
            s = BeautifulSoup(r.text, 'html.parser')
            
            # Method 1: __NUXT_DATA__ script if present
            nuxt_script = s.find('script', id='__NUXT_DATA__')
            if nuxt_script:
                try:
                    data = json.loads(nuxt_script.text)
                    if isinstance(data, list):
                        resolved_cache = {}
                        def resolve(idx, path=None):
                            if path is None:
                                path = set()
                            if idx in resolved_cache:
                                return resolved_cache[idx]
                            if idx is None:
                                return None
                            if not isinstance(idx, int) or idx < 0 or idx >= len(data):
                                return idx
                            if idx in path:
                                return f"Circular({idx})"
                            val = data[idx]
                            path.add(idx)
                            if val is None:
                                res = None
                            elif isinstance(val, (str, int, float, bool)):
                                res = val
                            elif isinstance(val, list):
                                res = [resolve(item, path.copy()) for item in val]
                            elif isinstance(val, dict):
                                res = {k: resolve(v, path.copy()) for k, v in val.items()}
                            else:
                                res = val
                            resolved_cache[idx] = res
                            return res
                            
                        for idx, item in enumerate(data):
                            if isinstance(item, dict) and "productId" in item:
                                p = resolve(idx)
                                if not isinstance(p, dict):
                                    continue
                                    
                                product_id = str(p.get("productId"))
                                if not product_id or product_id in seen_ids:
                                    continue
                                    
                                title = p.get("fullTitle") or p.get("title") or ""
                                brand_name = p.get("brand", {}).get("name") if isinstance(p.get("brand"), dict) else None
                                if brand_name and brand_name not in title:
                                    title = f"{brand_name} {title}".strip()
                                    
                                if not title:
                                    continue
                                    
                                price_info = p.get("price")
                                price = None
                                discount_percentage = None
                                badge = None
                                
                                if isinstance(price_info, dict):
                                    price = price_info.get("price")
                                    discount = price_info.get("discount")
                                    if isinstance(discount, dict):
                                        discount_percentage = discount.get("percentageDiscount")
                                        badge = discount.get("bargainHintText")
                                        
                                if price is None:
                                    continue
                                    
                                image_url = p.get("image") or ""
                                keyfacts = p.get("keyfacts")
                                description = ""
                                if isinstance(keyfacts, dict):
                                    description = clean_text(keyfacts.get("description") or keyfacts.get("keyfacts") or "")
                                if not description:
                                    description = clean_text(p.get("description") or "")
                                    
                                valid_from, valid_until = extract_lidl_validity(p)
                                    
                                seen_ids.add(product_id)
                                offers.append({
                                    "id": f"lidl-{product_id}",
                                    "title": title,
                                    "price": price,
                                    "app_price": None,
                                    "discount_percentage": discount_percentage,
                                    "image_url": image_url,
                                    "description": description,
                                    "base_price": None,
                                    "badge": badge,
                                    "valid_from": valid_from,
                                    "valid_until": valid_until
                                })
                except Exception as nuxt_err:
                    print(f"Error parsing Nuxt data on {url}: {nuxt_err}")
            
            # Method 2: Inline data-grid-data attributes (commonly used on some campaign landing pages)
            grid_divs = s.find_all('div', attrs={"data-grid-data": True})
            for div in grid_divs:
                try:
                    raw_json = html.unescape(div["data-grid-data"])
                    p = json.loads(raw_json)
                    if not isinstance(p, dict):
                        continue
                        
                    product_id = str(p.get("productId"))
                    if not product_id or product_id in seen_ids:
                        continue
                        
                    title = p.get("fullTitle") or p.get("title") or ""
                    brand_name = p.get("brand", {}).get("name") if isinstance(p.get("brand"), dict) else None
                    if brand_name and brand_name not in title:
                        title = f"{brand_name} {title}".strip()
                        
                    if not title:
                        continue
                        
                    price_info = p.get("price")
                    price = None
                    discount_percentage = None
                    badge = None
                    
                    if isinstance(price_info, dict):
                        price = price_info.get("price")
                        discount = price_info.get("discount")
                        if isinstance(discount, dict):
                            discount_percentage = discount.get("percentageDiscount")
                            badge = discount.get("bargainHintText")
                            
                    if price is None:
                        continue
                        
                    image_url = p.get("image") or ""
                    keyfacts = p.get("keyfacts")
                    description = ""
                    if isinstance(keyfacts, dict):
                        description = clean_text(keyfacts.get("description") or keyfacts.get("keyfacts") or "")
                    if not description:
                        description = clean_text(p.get("description") or "")
                        
                    valid_from, valid_until = extract_lidl_validity(p)
                        
                    seen_ids.add(product_id)
                    offers.append({
                        "id": f"lidl-{product_id}",
                        "title": title,
                        "price": price,
                        "app_price": None,
                        "discount_percentage": discount_percentage,
                        "image_url": image_url,
                        "description": description,
                        "base_price": None,
                        "badge": badge,
                        "valid_from": valid_from,
                        "valid_until": valid_until
                    })
                except Exception as div_err:
                    pass
                    
        except Exception as ex:
            print(f"Error scraping Lidl campaign {url}: {ex}")
            
    return offers

# Supermarket Provider Registry
PROVIDERS = {
    "edeka": {
        "search": search_edeka_markets,
        "scrape": scrape_edeka_offers
    },
    "lidl": {
        "search": search_lidl_markets,
        "scrape": scrape_lidl_offers
    }
}

def update_market_offers_in_db(market_id: str, session: Session) -> bool:
    """
    Scrape offers for a market and update them in the database using the Provider Registry.
    """
    # 1. Fetch market from DB
    market = session.get(Market, market_id)
    if not market:
        return False
        
    # Determine provider from market_id prefix
    provider_name = "edeka"
    if market_id.startswith("lidl-"):
        provider_name = "lidl"
        
    provider = PROVIDERS.get(provider_name, PROVIDERS["edeka"])
    
    # 2. Scrape offers from provider
    offers_data = provider["scrape"](market.offers_url, market_id=market_id)
    if not offers_data:
        return False
        
    # 3. Delete old offers for this market, tracking old IDs to detect new offers
    old_offers = session.exec(select(Offer).where(Offer.market_id == market_id)).all()
    old_offer_ids = {o.id for o in old_offers}
    for o in old_offers:
        session.delete(o)
    session.commit()
    
    # 4. Insert new offers
    for o_data in offers_data:
        offer = Offer(
            id=o_data["id"],
            market_id=market_id,
            title=o_data["title"],
            price=o_data["price"],
            app_price=o_data.get("app_price"),
            discount_percentage=o_data.get("discount_percentage"),
            image_url=o_data.get("image_url"),
            description=o_data.get("description"),
            base_price=o_data.get("base_price"),
            badge=o_data.get("badge"),
            valid_from=o_data.get("valid_from"),
            valid_until=o_data.get("valid_until")
        )
        session.add(offer)
        
    # 5. Update market last_scraped
    market.last_scraped = datetime.utcnow()
    session.add(market)
    session.commit()

    # 6. Check for favorite product notifications on new offers
    try:
        from app.database import FavoriteProduct
        from app.notifications.manager import notify_new_offers
        
        favorite_products = session.exec(select(FavoriteProduct)).all()
        if favorite_products:
            matching_new_offers = []
            for o_data in offers_data:
                if o_data["id"] not in old_offer_ids:
                    title_lower = o_data["title"].lower()
                    desc_lower = (o_data["description"] or "").lower()
                    for prod in favorite_products:
                        prod_lower = prod.name.lower()
                        if prod_lower in title_lower or prod_lower in desc_lower:
                            matching_new_offers.append(o_data)
                            break
                            
            if matching_new_offers:
                notify_new_offers(session, market.name, matching_new_offers)
    except Exception as notify_err:
        print(f"Error triggering notifications in scraper: {notify_err}")

    return True
