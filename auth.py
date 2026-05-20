"""
auth.py  —  Upstox OAuth2 Authentication Helper

HOW IT WORKS:
1. Run this script once daily before 9:15 AM:  python auth.py
2. It opens your browser to the Upstox login page.
3. After you log in, Upstox redirects to http://127.0.0.1:5000/callback
4. This script captures the auth code, exchanges it for an access token,
   and saves it to token.txt.
5. The main scanner reads the token from token.txt.
"""

import os
import webbrowser
import requests
import threading
from flask import Flask, request as flask_request
from config import (
    UPSTOX_API_KEY, UPSTOX_API_SECRET,
    UPSTOX_REDIRECT_URI, TOKEN_FILE
)

app = Flask(__name__)
_access_token = None
_auth_done = threading.Event()


def get_auth_url() -> str:
    """Build the Upstox OAuth2 login URL."""
    return (
        "https://api-v2.upstox.com/login/authorization/dialog"
        f"?response_type=code"
        f"&client_id={UPSTOX_API_KEY}"
        f"&redirect_uri={UPSTOX_REDIRECT_URI}"
    )


def exchange_code_for_token(code: str) -> str:
    """Exchange authorization code for access token."""
    url = "https://api-v2.upstox.com/login/authorization/token"
    headers = {
        "accept":       "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "code":          code,
        "client_id":     UPSTOX_API_KEY,
        "client_secret": UPSTOX_API_SECRET,
        "redirect_uri":  UPSTOX_REDIRECT_URI,
        "grant_type":    "authorization_code",
    }
    resp = requests.post(url, headers=headers, data=data)
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return token


@app.route("/callback")
def callback():
    global _access_token
    code = flask_request.args.get("code")
    if not code:
        return "<h2>❌ No auth code received. Close this tab and try again.</h2>", 400

    try:
        _access_token = exchange_code_for_token(code)
        with open(TOKEN_FILE, "w") as f:
            f.write(_access_token)
        print(f"\n✅ Access token saved to {TOKEN_FILE}")
        _auth_done.set()
        return "<h2>✅ Authentication successful! You can close this tab now.</h2>"
    except Exception as e:
        return f"<h2>❌ Error: {e}</h2>", 500


def run_flask():
    app.run(port=5000, debug=False, use_reloader=False)


def authenticate() -> str:
    """Full OAuth2 flow. Opens browser, waits for callback, returns token."""
    if os.path.exists(TOKEN_FILE):
        choice = input(f"Found existing token in {TOKEN_FILE}. Use it? (y/n): ").strip().lower()
        if choice == "y":
            with open(TOKEN_FILE) as f:
                token = f.read().strip()
            print("✅ Loaded existing token.")
            return token

    # Start Flask in background thread
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

    auth_url = get_auth_url()
    print(f"\n🔗 Opening browser for Upstox login...\n   URL: {auth_url}\n")
    webbrowser.open(auth_url)

    print("⏳ Waiting for you to log in...")
    _auth_done.wait(timeout=300)  # wait up to 5 minutes

    if _access_token:
        return _access_token
    else:
        raise TimeoutError("Authentication timed out after 5 minutes.")


def load_token() -> str:
    """Load access token from file (used by other modules)."""
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError(
            "❌ token.txt not found. Run 'python auth.py' first to authenticate."
        )
    with open(TOKEN_FILE) as f:
        return f.read().strip()


if __name__ == "__main__":
    token = authenticate()
    print(f"\n🔑 Token: {token[:30]}...  (saved to {TOKEN_FILE})")
