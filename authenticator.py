"""
Authenticator — owns ALL credentials and auth. The worker only *requests* what it needs;
this module reads the secret files, loads keys, and performs the strap ECDH handshake.
It is the ONLY module that imports `helio.load_auth_key` / `oura.maybe_token` or reads
the secret files (secret-keys.local.txt, oura-token.local.txt).
"""
import helio
helio.DEBUG = False
from helio import HelioClient, load_auth_key
import oura


class Authenticator:
    # ---- strap (BLE) ----
    async def strap_session(self):
        """Load the 16-byte AUTH_KEY, build a HelioClient, run the ECDH-B163 handshake,
        and return a READY, authed client — or None if the strap isn't found / auth fails.
        The ECDH session key is negotiated per connection inside connect_and_auth(); we
        cache nothing."""
        try:
            key = load_auth_key()                    # reads secret-keys.local.txt
        except SystemExit:
            return None
        client = HelioClient(key)
        try:
            ok = await client.connect_and_auth()     # connect_and_auth sys.exit()s if not found
        except SystemExit:
            ok = False
        except Exception:
            ok = False
        if not ok:
            try:
                await client.close()
            except Exception:
                pass
            return None
        return client

    # ---- oura (cloud token) ----
    def oura_token(self):
        """The Oura Personal Access Token (env OURA_TOKEN or oura-token.local.txt), or None."""
        return oura.maybe_token()

    def is_oura_available(self):
        return self.oura_token() is not None
