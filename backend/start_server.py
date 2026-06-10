"""
Wrapper that sets sys.path explicitly before importing uvicorn,
bypassing the getcwd() permission issue in iCloud Drive paths.
"""
import os
import sys

# Resolve the backend directory from this file's location
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

# Remove empty/relative entries from sys.path that trigger getcwd()
sys.path = [p for p in sys.path if p and os.path.isabs(p)]

# Ensure our backend package is findable
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Run from the backend directory so .env loading and the relative
# sqlite DATABASE_URL resolve to the same paths alembic used.
os.chdir(BACKEND_DIR)
os.makedirs("data", exist_ok=True)

# Now import and run uvicorn
import uvicorn  # noqa: E402

if __name__ == "__main__":
    # Set PYTHONPATH so workers/subprocesses also find the app
    os.environ["PYTHONPATH"] = BACKEND_DIR

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        loop="asyncio",
        http="h11",
        ws="websockets",
    )
