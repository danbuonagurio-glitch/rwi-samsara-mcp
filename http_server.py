"""
Remote (Streamable HTTP) entrypoint for the Samsara MCP server.

Reuses every tool defined in server.py. Adds:
  - Secret-path auth: endpoint is /mcp/<MCP_SECRET>. Claude.ai custom
    connectors can't send custom headers, so the secret lives in the URL.
    A Bearer header with the same secret is also accepted (Desktop/Code).
  - READ_ONLY mode (default on): hides and blocks create/update tools.

Env:
  SAMSARA_API_TOKEN  required  Samsara API token (use a read-only token)
  MCP_SECRET         required  long random string, e.g. `openssl rand -hex 32`
  READ_ONLY          optional  "false" to expose write tools (default "true")
  PORT               optional  default 8080
"""

import contextlib
import hmac
import os
import sys

import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

import server as samsara  # existing tool definitions

WRITE_TOOLS = {"update_vehicle", "create_driver", "update_driver", "create_tag"}

MCP_SECRET = os.getenv("MCP_SECRET", "")
READ_ONLY = os.getenv("READ_ONLY", "true").lower() != "false"

if len(MCP_SECRET) < 32:
    sys.exit("ERROR: MCP_SECRET must be set and at least 32 characters.")
try:
    samsara.get_samsara_client()
except ValueError as e:
    sys.exit(f"ERROR: {e}")

# --- Read-only filtering: re-register handlers over the originals ---------
_orig_list = samsara.list_tools
_orig_call = samsara.call_tool

if READ_ONLY:
    @samsara.server.list_tools()
    async def _list_tools():
        return [t for t in await _orig_list() if t.name not in WRITE_TOOLS]

    @samsara.server.call_tool()
    async def _call_tool(name, arguments):
        if name in WRITE_TOOLS:
            raise ValueError(f"'{name}' is disabled (READ_ONLY mode).")
        return await _orig_call(name, arguments)

# --- Transport ------------------------------------------------------------
manager = StreamableHTTPSessionManager(
    app=samsara.server,
    stateless=True,
    json_response=True,
    security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


class SecretGate:
    """ASGI gate: path must be /mcp/<secret> or carry Bearer <secret>."""

    def __init__(self, app):
        self.app = app
        self.prefix = f"/mcp/{MCP_SECRET}"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode()
        bearer_ok = auth.startswith("Bearer ") and hmac.compare_digest(
            auth[7:], MCP_SECRET
        )
        if path.rstrip("/") == self.prefix or path.startswith(self.prefix + "/"):
            scope = dict(scope, path="/", raw_path=b"/")
            return await manager.handle_request(scope, receive, send)
        if path.rstrip("/") == "/mcp" and bearer_ok:
            scope = dict(scope, path="/", raw_path=b"/")
            return await manager.handle_request(scope, receive, send)
        await JSONResponse({"error": "not found"}, status_code=404)(scope, receive, send)


async def health(_):
    return PlainTextResponse("ok")


@contextlib.asynccontextmanager
async def lifespan(_app):
    async with manager.run():
        yield


app = Starlette(
    routes=[Route("/healthz", health), Mount("/", app=SecretGate(None))],
    lifespan=lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
