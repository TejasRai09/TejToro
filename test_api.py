import sys
import codecs
sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
import requests
from auth import load_token

def test_api():
    BASE_URL = "https://api-v2.upstox.com"
    token = load_token()
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    url = f"{BASE_URL}/market-quote/quotes"
    params = {"instrument_key": "NSE_EQ|INE002A01018"} # Reliance
    
    print("Fetching quote...")
    resp = requests.get(url, headers=headers, params=params)
    print("Status:", resp.status_code)
    print("Response:", resp.text)

if __name__ == '__main__':
    test_api()
