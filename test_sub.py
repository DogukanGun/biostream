"""Test the live-HR GraphQL subscription over WebSocket (graphql-transport-ws)."""
import asyncio
import json

import websockets


async def main():
    uri = "ws://127.0.0.1:8000/graphql"
    async with websockets.connect(uri, subprotocols=["graphql-transport-ws"]) as ws:
        await ws.send(json.dumps({"type": "connection_init"}))
        ack = json.loads(await ws.recv())
        print("connection:", ack.get("type"))
        await ws.send(json.dumps({
            "id": "1", "type": "subscribe",
            "payload": {"query": "subscription { heartRateLive { ts bpm } }"}}))
        got = 0
        while got < 3:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
            if msg["type"] == "next":
                p = msg["payload"]["data"]["heartRateLive"]
                print(f"  push: ts={p['ts']} bpm={p['bpm']}")
                got += 1
            elif msg["type"] == "error":
                print("error:", msg.get("payload"))
                return
        await ws.send(json.dumps({"id": "1", "type": "complete"}))
    print("\nsubscription works — live HR pushed over WebSocket")


if __name__ == "__main__":
    asyncio.run(main())
