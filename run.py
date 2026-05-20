"""
run.py — Start VWAP Scanner (backend + frontend) with one command.
Usage:  python run.py
"""
import subprocess
import sys
import os
import time
import webbrowser

ROOT     = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(ROOT, "frontend")
NPM      = "npm.cmd" if os.name == "nt" else "npm"

print("\n  ⚡  VWAP Scanner — starting up...\n")

backend  = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "server:app", "--reload", "--port", "8000"],
    cwd=ROOT,
)
frontend = subprocess.Popen(
    [NPM, "run", "dev"],
    cwd=FRONTEND,
)

time.sleep(4)
webbrowser.open("http://localhost:5173")

print("  ✅  Backend  → http://localhost:8000")
print("  ✅  Frontend → http://localhost:5173")
print("\n  Press Ctrl+C to stop both servers.\n")

try:
    backend.wait()
    frontend.wait()
except KeyboardInterrupt:
    print("\n  Shutting down...")
    backend.terminate()
    frontend.terminate()
    backend.wait()
    frontend.wait()
    print("  Done.\n")
