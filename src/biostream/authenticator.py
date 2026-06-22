"""
Authenticator — owns auth. The worker only *requests*; this performs it. Reads no secret
files: credentials come from Config. The single auth facade.
"""
from . import helio
helio.DEBUG = False
from .helio import HelioClient


class Authenticator:
    def __init__(self, config):
        self.config = config

    async def strap_session(self):
        """Build a HelioClient with the configured key + strap name, run the ECDH handshake,
        and return a ready authed client — or None if the strap isn't found / auth fails."""
        client = HelioClient(self.config.auth_key, strap_name=self.config.strap_name)
        try:
            ok = await client.connect_and_auth()
        except Exception:
            ok = False
        if not ok:
            try:
                await client.close()
            except Exception:
                pass
            return None
        return client

    def oura_token(self):
        return self.config.oura_token

    def is_oura_available(self):
        return bool(self.config.oura_token)
