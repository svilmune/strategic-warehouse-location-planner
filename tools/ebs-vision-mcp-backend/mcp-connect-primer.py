"""Startup primer: establish the process-global MCP DB connection so SQLcl
run-sql works immediately after a service restart. The SQLcl MCP server starts
with no connection; calling the connect tool once primes it for all subsequent
client sessions until the next restart."""
import asyncio, sys
from mcp.client.sse import sse_client
from mcp import ClientSession

URL = "http://127.0.0.1:8081/sse"
CONN = "EBSDB_MCP"

async def prime():
    async with sse_client(URL) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("connect", {"connection_name": CONN, "model": "startup-primer"})
            if getattr(res, "isError", False):
                txt = res.content[0].text if res.content else ""
                print("primer: connect error:", txt[:200]); return 1
            print("primer: connected", CONN); return 0

async def main():
    for attempt in range(15):
        try:
            sys.exit(await prime())
        except Exception as e:
            print(f"primer attempt {attempt+1}: {e!r}"); await asyncio.sleep(2)
    print("primer: gave up after retries"); sys.exit(1)

asyncio.run(main())
