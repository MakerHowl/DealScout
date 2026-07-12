from app.scraper import search_edeka_markets

def inspect():
    markets = search_edeka_markets("72336")
    for m in markets:
        print(f"ID: {m['id']}")
        print(f"Name: {m['name']}")
        print(f"URL: {m['url']}")
        print(f"Offers URL: {m['offers_url']}")
        print("-" * 40)

if __name__ == "__main__":
    inspect()
