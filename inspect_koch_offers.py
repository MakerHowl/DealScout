from curl_cffi import requests
from bs4 import BeautifulSoup

def inspect_koch_offers():
    url = "https://www.kochmarkt.de/angebote/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
    }
    
    try:
        r = requests.get(url, headers=headers, impersonate="chrome110", verify=False)
        print(f"Status Code: {r.status_code}")
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Look for dialogs or iframe or scripts
        dialogs = soup.find_all('dialog')
        print(f"Number of <dialog> tags: {len(dialogs)}")
        
        iframes = soup.find_all('iframe')
        print("--- IFRAMES ---")
        for iframe in iframes:
            print(f"Iframe src: {iframe.get('src', '')}")
            
        print("--- CONTENT SNIPPET ---")
        # Print first 1000 chars of body
        body = soup.find('body')
        if body:
            print(body.text[:1000].strip())
            
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    inspect_koch_offers()
