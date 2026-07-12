from curl_cffi import requests

def inspect_raw():
    url = "https://www.edeka.de/api/marketsearch/markets"
    params = {"searchstring": "72336"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.edeka.de/marktsuche.jsp",
    }
    
    response = requests.get(url, params=params, headers=headers, impersonate="chrome110", verify=False)
    if response.status_code == 200:
        data = response.json()
        markets = data.get("markets", [])
        for m in markets:
            if "KOCHmarkt Balingen" in m.get("name", ""):
                import pprint
                pprint.pprint(m)
                break

if __name__ == "__main__":
    inspect_raw()
