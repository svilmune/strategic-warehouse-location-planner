"""Copilot Studio <-> Foundry agent <-> private MCP server shim."""
import os
import logging

import azure.functions as func
from azurefunctions.extensions.http.fastapi import (
    Request,
    Response,
    StreamingResponse,
    JSONResponse,
)


app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


_creds = None
_agents_client = None


def _agents():
    global _creds, _agents_client
    if _agents_client is None:
        from azure.identity import DefaultAzureCredential
        from azure.ai.agents import AgentsClient
        endpoint = os.environ["FOUNDRY_ENDPOINT"]
        if _creds is None:
            _creds = DefaultAzureCredential()
        _agents_client = AgentsClient(endpoint=endpoint, credential=_creds)
    return _agents_client


@app.route(route="hello", methods=[func.HttpMethod.GET])
async def hello(req: Request) -> Response:
    return Response(content="hello world", media_type="text/plain")


@app.route(route="ask", methods=[func.HttpMethod.POST])
async def ask(req: Request) -> JSONResponse:
    """Copilot Studio entry. Polls the run and auto-approves MCP tool calls
    until the run completes. /assistants store doesn't accept
    require_approval on MCP tools, so we approve them server-side."""
    import time
    import httpx
    from azure.identity import DefaultAzureCredential
    from azure.ai.agents.models import RunStatus, MessageRole

    asst = os.environ.get("ASSISTANT_ID", "")
    if not asst:
        return JSONResponse(
            {"error": "ASSISTANT_ID not configured"}, status_code=503,
        )

    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "invalid json body"}, status_code=400)

    question = (body.get("question") or "").strip()
    thread_id = body.get("conversation_id")
    if not question:
        return JSONResponse({"error": "missing 'question'"}, status_code=400)

    agents = _agents()
    if not thread_id:
        thread_id = agents.threads.create().id
    agents.messages.create(thread_id=thread_id, role="user", content=question)
    run = agents.runs.create(thread_id=thread_id, agent_id=asst)
    run_id = run.id

    # Poll + auto-approve loop. The SDK's create_and_process doesn't yet
    # handle MCP submit_tool_approval, so we drive it via raw HTTP.
    base = os.environ["FOUNDRY_ENDPOINT"]
    cred = DefaultAzureCredential()
    api = "api-version=2025-05-15-preview"
    deadline = time.time() + 180  # 3-min ceiling per /ask call

    async with httpx.AsyncClient(timeout=15) as c:
        while True:
            if time.time() > deadline:
                return JSONResponse(
                    {"error": "run timed out", "thread_id": thread_id,
                     "run_id": run_id, "last_status": str(run.status)},
                    status_code=504,
                )

            tok = cred.get_token("https://ai.azure.com/.default").token
            r = await c.get(
                f"{base}/threads/{thread_id}/runs/{run_id}?{api}",
                headers={"Authorization": f"Bearer {tok}"},
            )
            if r.status_code != 200:
                return JSONResponse(
                    {"error": "poll_failed", "status": r.status_code,
                     "body": r.text[:400]}, status_code=502)
            run = r.json()
            status = run.get("status")

            if status in ("completed",):
                break
            if status in ("failed", "cancelled", "expired"):
                return JSONResponse(
                    {"error": f"run {status}",
                     "detail": str(run.get("last_error"))},
                    status_code=502)

            if status == "requires_action":
                ra = run.get("required_action") or {}
                if ra.get("type") == "submit_tool_approval":
                    calls = ra["submit_tool_approval"].get("tool_calls", [])
                    approvals = [{"tool_call_id": tc["id"], "approve": True}
                                 for tc in calls]
                    r = await c.post(
                        f"{base}/threads/{thread_id}/runs/{run_id}/submit_tool_outputs?{api}",
                        headers={"Authorization": f"Bearer {tok}",
                                 "Content-Type": "application/json"},
                        json={"tool_approvals": approvals},
                    )
                    if r.status_code >= 400:
                        return JSONResponse(
                            {"error": "approval_failed",
                             "status": r.status_code,
                             "body": r.text[:600],
                             "approvals": approvals},
                            status_code=502)
                    # loop will re-poll
                    continue

            # in_progress / queued — wait briefly
            await _async_sleep(2)

    # run completed — fetch the assistant reply
    answer = ""
    for m in agents.messages.list(thread_id=thread_id, order="desc", limit=10):
        if m.role == MessageRole.AGENT:
            answer = " ".join(
                b.text.value for b in m.content if hasattr(b, "text")
            )
            break

    return JSONResponse({"answer": answer, "conversation_id": thread_id})


async def _async_sleep(s: float):
    import asyncio
    await asyncio.sleep(s)


@app.route(route="sse", methods=[func.HttpMethod.GET],
           auth_level=func.AuthLevel.ANONYMOUS)
async def mcp_sse(req: Request) -> StreamingResponse:
    # Anonymous on purpose (2026-05-27): Foundry's Responses-API MCP Connector
    # strips ?code= query strings before calling the MCP server's /sse endpoint.
    # /messages/ was already anonymous; making /sse anonymous to match restores
    # the handshake. The Function App's network-layer protections (VNet
    # integration to private MCP backend, optional IP allowlist on this Function
    # App) replace the per-route function key as the security boundary.
    # See docs/foundry-mcp-lessons-learned.md § Blocker 6 + Microsoft docs:
    # https://learn.microsoft.com/azure/azure-functions/functions-mcp-foundry-tools
    backend = os.environ["MCP_BACKEND_URL"]

    async def stream():
        import httpx
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "GET", backend, headers={"Accept": "text/event-stream"}
            ) as upstream:
                async for chunk in upstream.aiter_bytes():
                    yield chunk

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.route(route="setup/clone-agent", methods=[func.HttpMethod.POST])
async def clone_agent(req: Request) -> JSONResponse:
    """One-shot Phase-3 helper. Wraps everything in try/except so the Python
    error makes it back as JSON instead of a generic 500."""
    import traceback
    try:
        import httpx
        from azure.identity import DefaultAzureCredential

        try:
            body = await req.json()
        except Exception:
            body = {}
        mcp_url = (body.get("mcp_url") or "").strip()
        if not mcp_url:
            return JSONResponse({"error": "missing 'mcp_url'"}, status_code=400)

        base = os.environ["FOUNDRY_ENDPOINT"]
        cred = DefaultAzureCredential()
        token = cred.get_token("https://ai.azure.com/.default").token
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"{base}/agents/ebs-vision-agent?api-version=2025-05-15-preview",
                headers=headers,
            )
            if r.status_code != 200:
                return JSONResponse(
                    {"step": "fetch_agent", "status": r.status_code,
                     "body": r.text[:600]},
                    status_code=500,
                )
            live = r.json()
            try:
                instructions = live["versions"]["latest"]["definition"]["instructions"]
            except KeyError:
                return JSONResponse(
                    {"step": "parse_agent",
                     "shape_top": list(live.keys())[:20],
                     "raw": str(live)[:600]},
                    status_code=500,
                )

            clone_body = {
                "name": "ebs-vision-agent-asst",
                "description": "Assistants-API mirror of ebs-vision-agent for Function-driven Copilot Studio invocation.",
                "model": "gpt-4.1-1",
                "instructions": instructions,
                "tools": [{
                    "type": "mcp",
                    "server_label": "ebs_vision_mcp",
                    "server_url": mcp_url,
                }],
            }
            r = await c.post(
                f"{base}/assistants?api-version=2025-05-15-preview",
                headers={**headers, "Content-Type": "application/json"},
                json=clone_body,
            )
            if r.status_code >= 400:
                return JSONResponse(
                    {"step": "create_assistant", "status": r.status_code,
                     "body": r.text[:600]},
                    status_code=500,
                )
            out = r.json()
            return JSONResponse({
                "asst_id": out.get("id"),
                "name": out.get("name"),
                "model": out.get("model"),
                "instructions_len": len(out.get("instructions") or ""),
                "tools_count": len(out.get("tools") or []),
            })
    except Exception as e:
        return JSONResponse(
            {"step": "uncaught", "error_type": type(e).__name__,
             "error_msg": str(e)[:600],
             "trace": traceback.format_exc()[-1500:]},
            status_code=500,
        )


@app.route(route="messages/", methods=[func.HttpMethod.POST],
           auth_level=func.AuthLevel.ANONYMOUS)
async def mcp_messages(req: Request) -> Response:
    # Anonymous on purpose: Foundry's MCP client constructs the messages URL
    # from the SSE endpoint event ("/messages/?session_id=…") and does not
    # carry the ?code= function key over from the SSE URL. Gating is via the
    # opaque session_id (random hex generated by mcp-proxy on the open SSE
    # channel — invalid session IDs reject upstream with 400).
    import httpx
    base = os.environ["MCP_BACKEND_URL"]
    backend = base.rsplit("/sse", 1)[0] + "/messages/"

    qs = "&".join(
        f"{k}={v}" for k, v in req.query_params.items() if k != "code"
    )
    if qs:
        backend += "?" + qs

    body_bytes = await req.body()
    content_type = req.headers.get("content-type", "application/json")

    async with httpx.AsyncClient(timeout=60) as client:
        upstream = await client.post(
            backend, content=body_bytes,
            headers={"Content-Type": content_type},
        )

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )
