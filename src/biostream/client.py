"""Client — a small convenience wrapper around Config + serve/collect/app."""
import asyncio

from .config import Config
from .api import create_app
from .worker import run_worker
from .server import serve


class Client:
    def __init__(self, config=None, **kwargs):
        self.config = config or Config.from_env(**kwargs)

    def serve(self):
        """Run worker + GraphQL gateway together (blocking)."""
        serve(self.config)

    def collect(self):
        """Run only the background collector (no API), blocking."""
        asyncio.run(run_worker(self.config))

    def app(self):
        """Return the FastAPI app (GraphQL only — no worker) for custom ASGI hosting."""
        return create_app(self.config)
