"""biostream command line: serve / scan / fetch-key."""
import argparse
import asyncio


def _serve(args):
    from .config import Config
    from .server import serve
    cfg = Config.from_env(
        auth_key=args.auth_key, oura_token=args.oura_token, strap_name=args.strap_name,
        data_dir=args.data_dir, host=args.host, port=args.port,
        zepp_email=args.zepp_email, zepp_password=args.zepp_password,
    )
    print(f"biostream: data_dir={cfg.data_dir}  ->  http://{cfg.host}:{cfg.port}/graphql")
    serve(cfg)


def _scan(args):
    from bleak import BleakScanner

    async def run():
        print(f"Scanning {args.seconds:.0f}s for BLE devices...")
        found = await BleakScanner.discover(timeout=args.seconds, return_adv=True)
        rows = sorted(
            ((adv.rssi, addr, (adv.local_name or dev.name or "(no name)"))
             for addr, (dev, adv) in found.items()),
            key=lambda r: r[0], reverse=True)
        for rssi, addr, name in rows:
            print(f"  {rssi:>4} dBm  {name:28}  {addr}")
        print("\nPass part of your strap's name as --strap-name (e.g. 'helio').")
    asyncio.run(run())


def _fetch_key(args):
    from .keys import fetch_zepp_key
    key = fetch_zepp_key(args.email, args.password, args.method)
    print("auth_key = 0x" + key.hex())


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="biostream",
        description="Collect Amazfit/Zepp strap (BLE) + Oura cloud health data and serve it over GraphQL.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the worker + GraphQL gateway in one process")
    s.add_argument("--auth-key", help="16-byte strap key as hex (0x..)")
    s.add_argument("--oura-token", help="Oura personal access token")
    s.add_argument("--strap-name", help="BLE name substring of your strap (default: helio)")
    s.add_argument("--data-dir", help="where to store helio.db + json (default: platform data dir)")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--zepp-email", help="fetch the auth key by logging into Zepp")
    s.add_argument("--zepp-password")
    s.set_defaults(func=_serve)

    sc = sub.add_parser("scan", help="list nearby BLE devices to find your strap's name")
    sc.add_argument("--seconds", type=float, default=12.0)
    sc.set_defaults(func=_scan)

    fk = sub.add_parser("fetch-key", help="fetch the strap auth key via a Zepp login")
    fk.add_argument("--email", required=True)
    fk.add_argument("--password", required=True)
    fk.add_argument("--method", default="amazfit", choices=["amazfit", "xiaomi"])
    fk.set_defaults(func=_fetch_key)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
