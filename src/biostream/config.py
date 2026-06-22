"""
Config — the single source of truth for credentials, paths, and tuning.
Threaded into every module so nothing keeps __file__-relative constants or reads secret files.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import platformdirs

APP_NAME = "biostream"


@dataclass
class Config:
    # credentials
    auth_key: object = None            # hex str ("0x.."/"..") or 16 raw bytes; or None to fetch via zepp creds
    oura_token: Optional[str] = None
    # device
    strap_name: str = "helio"          # BLE local-name substring filter (case-insensitive)
    # storage
    data_dir: object = None            # Path|str; default = platform user-data dir
    # oura
    oura_api_url: str = "https://api.ouraring.com/v2/usercollection/"
    oura_days: int = 30
    # collection tuning
    resync_interval: int = 1800        # seconds between history re-syncs
    days_back: int = 14                # first-sync window
    history_max: int = 600             # live HR trail length
    # server
    host: str = "127.0.0.1"
    port: int = 8000
    # optional: fetch the strap auth key by logging into Zepp
    zepp_email: Optional[str] = None
    zepp_password: Optional[str] = None
    zepp_method: str = "amazfit"

    def __post_init__(self):
        if self.auth_key is None and self.zepp_email and self.zepp_password:
            from .keys import fetch_zepp_key
            self.auth_key = fetch_zepp_key(self.zepp_email, self.zepp_password, self.zepp_method)
        if self.auth_key is None:
            raise ValueError("auth_key required (hex str or 16 bytes), "
                             "or provide zepp_email + zepp_password to fetch it")
        if isinstance(self.auth_key, str):
            self.auth_key = bytes.fromhex(self.auth_key.removeprefix("0x").removeprefix("0X"))
        self.auth_key = bytes(self.auth_key)
        if len(self.auth_key) != 16:
            raise ValueError(f"auth_key must be 16 bytes, got {len(self.auth_key)}")
        if self.data_dir is None:
            self.data_dir = platformdirs.user_data_dir(APP_NAME)
        self.data_dir = Path(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "helio.db"

    @property
    def live_json(self) -> Path:
        return self.data_dir / "live.json"

    @property
    def history_json(self) -> Path:
        return self.data_dir / "history.json"

    @property
    def oura_json(self) -> Path:
        return self.data_dir / "oura.json"

    @property
    def insights_json(self) -> Path:
        return self.data_dir / "insights.json"

    @classmethod
    def from_env(cls, *, auth_key=None, oura_token=None, strap_name=None, data_dir=None,
                 host=None, port=None, zepp_email=None, zepp_password=None, **kw):
        """Build a Config from explicit args, falling back to environment variables."""
        return cls(
            auth_key=auth_key or os.environ.get("ZEPP_AUTH_KEY") or os.environ.get("AUTH_KEY"),
            oura_token=oura_token or os.environ.get("OURA_TOKEN"),
            strap_name=strap_name or os.environ.get("STRAP_NAME") or "helio",
            data_dir=data_dir or os.environ.get("DATA_DIR"),
            host=host or os.environ.get("HOST") or "127.0.0.1",
            port=int(port or os.environ.get("PORT") or 8000),
            zepp_email=zepp_email or os.environ.get("ZEPP_EMAIL"),
            zepp_password=zepp_password or os.environ.get("ZEPP_PASSWORD"),
            **kw,
        )
