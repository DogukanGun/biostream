"""serve() — one call that runs the collector + GraphQL gateway in a single uvicorn process."""
import uvicorn

from .config import Config
from .api import create_app


def serve(config=None, **kwargs):
    """Run the worker + GraphQL API together (blocking). Pass a Config, or kwargs/env via from_env.

    Example:
        serve(auth_key="0x..", oura_token="..")        # GraphiQL at http://127.0.0.1:8000/graphql
    """
    if config is None:
        config = Config.from_env(**kwargs)
    app = create_app(config, run_worker=True)
    server = uvicorn.Server(uvicorn.Config(app, host=config.host, port=config.port, log_level="info"))
    server.run()
    return config
