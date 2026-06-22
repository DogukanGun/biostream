# biostream

Collect your **Amazfit/Zepp strap** (directly over Bluetooth) and your **Oura Ring** (cloud), store it
locally, and serve **everything over GraphQL** — including a live heart-rate subscription. One pip
install, one call.

## Install
```bash
pip install biostream
```

## Quickstart
```python
from biostream import serve

# you already have your 16-byte strap key + Oura token:
serve(auth_key="0x<32-hex-chars>", oura_token="<OURA_PAT>")
```
This starts the background collector **and** the GraphQL gateway in one process. Open the playground at
**http://127.0.0.1:8000/graphql**.

Don't have the strap key yet? Let biostream fetch it by logging into your Zepp account:
```python
serve(zepp_email="you@example.com", zepp_password="••••", oura_token="<OURA_PAT>")
```

## CLI
```bash
biostream serve --auth-key 0x.. --oura-token ..      # collect + serve
biostream scan                                        # find your strap's BLE name
biostream fetch-key --email .. --password ..          # get the 16-byte auth key via a Zepp login
```
Env vars also work: `ZEPP_AUTH_KEY` / `AUTH_KEY`, `OURA_TOKEN`, `STRAP_NAME`, `DATA_DIR`, `HOST`,
`PORT`, `ZEPP_EMAIL` / `ZEPP_PASSWORD`.

## Query it
```graphql
{
  live { connected hr battery steps today { restingHr sleepMinutes } }
  heartRate(limit: 50) { ts bpm }
  oura { nights { day totalH hrv restingHr } readiness { day score } }
  insights { nNights recovery }
}
```
Live stream (WebSocket subscription):
```graphql
subscription { heartRateLive { ts bpm } }
```
Time-series accept `start` / `end` (epoch ms) and `limit` (default 500, max 50000).

## What you get
- **Strap (BLE):** live HR + steps + battery, plus historical activity, resting/max HR, SpO₂, stress, PAI.
- **Oura (cloud):** sleep stages, HRV, resting HR, SpO₂, readiness, daily activity, intraday HR.
- **Insights:** a validated Recovery Score, FDR-corrected correlations and trends (improves as the strap
  accumulates a few days of data).
- **GraphQL gateway:** read-only, localhost-only, with a GraphiQL playground and a live-HR subscription.

## How it works
Components talk only through a local data dir (`~/.local/share/biostream` by default):
`worker` (collects) → `data/` (SQLite + JSON) → `api` (GraphQL). An `authenticator` owns all
credentials; nothing else reads your keys.

```python
from biostream import Config, run_worker, create_app
# advanced: run the collector and the API separately, or host create_app(config) under your own ASGI server
```

## Notes
- The strap must be **free** (not connected to the phone's Zepp app) while biostream runs — turn off
  phone Bluetooth.
- The gateway is **open but localhost-only**. Don't bind it to a public interface: it serves personal
  health data with no auth.
- Getting the strap key requires a one-time Zepp login (`fetch-key`). Unpairing the strap in the Zepp
  app invalidates the key.

MIT licensed. Built by reverse-engineering the Huami-2021 / Zepp OS BLE protocol; not affiliated with
Amazfit, Zepp, or Oura.
