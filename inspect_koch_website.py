from curl_cffi import requests
from bs4 import BeautifulSoup

def inspect_koch_site():
    url = "https://www.kochmarkt.de/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
    }
    
    try:
        r = requests.get(url, headers=headers, impersonate="chrome110", verify=False)
        print(f"Status Code: {r.status_code}")
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Look for links
        print("--- LINKS ---")
        links = soup.find_all('a')
        for link in links:
            href = link.get('href', '')
            text = link.text.strip()
            if href and any(x in href.lower() or x in text.lower() for x in ["angebot", "deal", "prospekt", "flyer", "werbung"]):
                print(f"Text: {text} | Href: {href}")
                
        # Look for iframes
        print("--- IFRAMES ---")
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src', '')
            print(f"Iframe src: {src}")
            
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    inspect_koch_site()
