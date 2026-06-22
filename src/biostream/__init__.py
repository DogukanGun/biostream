"""
biostream — collect Amazfit/Zepp strap (BLE) + Oura cloud health data and serve it over GraphQL.

Quickstart:
    from biostream import serve
    serve(auth_key="0x<16-bytes-hex>", oura_token="OURA_PAT")   # GraphiQL at :8000, worker streaming
    # or let it fetch the strap key for you:
    serve(zepp_email="you@example.com", zepp_password="..", oura_token="..")
"""
from .config import Config
from .api import create_app
from .worker import run_worker
from .keys import fetch_zepp_key
from .server import serve
from .client import Client

__version__ = "0.0.1"
__all__ = ["Config", "Client", "serve", "create_app", "run_worker", "fetch_zepp_key", "__version__"]
