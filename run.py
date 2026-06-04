"""
run.py — Start VWAP Scanner + Backtest Lab (backend + frontend) with one command.
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

print("\n  ⚡  TejToro — starting up...\n")

scanner  = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "server:app", "--reload", "--port", "8000"],
    cwd=ROOT,
)
backtest = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "backtest_server:app", "--reload", "--port", "8002"],
    cwd=ROOT,
)
frontend = subprocess.Popen(
    [NPM, "run", "dev"],
    cwd=FRONTEND,
)

time.sleep(4)
webbrowser.open("http://localhost:5173")

print("  ✅  Scanner backend   → http://localhost:8000")
print("  ✅  Backtest backend  → http://localhost:8002")
print("  ✅  Frontend          → http://localhost:5173")
print("\n  Press Ctrl+C to stop all servers.\n")

try:
    scanner.wait()
    backtest.wait()
    frontend.wait()
except KeyboardInterrupt:
    print("\n  Shutting down...")
    scanner.terminate()
    backtest.terminate()
    frontend.terminate()
    scanner.wait()
    backtest.wait()
    frontend.wait()
    print("  Done.\n")
