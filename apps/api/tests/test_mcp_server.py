from types import SimpleNamespace

import anyio
from fastapi import FastAPI, HTTPException
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import pytest

from app import mcp_tools as tools
from app.mcp_server import BearerMiddleware, CanonicalEndpoint, create_server
from starlette.routing import Route
from test_mcp_tools import mcp_data


@pytest.fixture
def transport_app(monkeypatch):
    monkeypatch.setenv("APP_URL", "http://localhost:8000")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("MCP_ENABLED", "true")
    state = {"revoked": False, "calls": 0}

    def verify(token, resource):
        state["calls"] += 1
        assert resource == "http://localhost:8000/mcp"
        if state["revoked"] or token not in {"aggregate", "detail", "transactions-only", "other", "no-scope"}:
            raise HTTPException(401)
        scopes = {"finance:read"} if token not in {"no-scope", "transactions-only"} else set()
        if token in {"detail", "transactions-only"}:
            scopes.add("finance:transactions")
        return SimpleNamespace(owner_id="owner-b" if token == "other" else "owner-a", scopes=frozenset(scopes), grant_id="grant")

    server = create_server()
    app = FastAPI()
    app.router.routes.append(Route("/mcp", endpoint=CanonicalEndpoint(BearerMiddleware(server.streamable_http_app(), verifier=verify)), methods=["GET", "POST", "DELETE", "OPTIONS"]))
    app.mount("/mcp", BearerMiddleware(server.streamable_http_app(), verifier=verify))
    return app, server, state


def authorization(value):
    return {"Authorization": f"Bearer {value}"}


def test_http_sdk_initialize_tools_prompts_resources(transport_app, mcp_data):
    app, server, state = transport_app

    async def run():
        async with server.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers=authorization("detail"), follow_redirects=True) as http:
                # Canonical /mcp must work directly, without a slash redirect.
                async with streamable_http_client("http://localhost:8000/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        initialized = await session.initialize()
                        assert initialized.serverInfo.name == "FinSight"
                        listed = await session.list_tools()
                        names = {item.name for item in listed.tools}
                        assert names == {"get_capabilities", "list_views", "get_import_freshness", "get_overview", "get_accounts",
                                         "search_transactions", "get_category_breakdown", "compare_periods", "get_recurring_payments",
                                         "get_savings_buckets", "get_upcoming_obligations", "get_financial_health"}
                        for item in listed.tools:
                            assert item.annotations.readOnlyHint is True
                            assert item.annotations.destructiveHint is False
                            assert item.annotations.openWorldHint is False
                            assert item.annotations.idempotentHint is True
                            assert item.outputSchema and item.inputSchema["additionalProperties"] is False
                            scope = [] if item.name in {"get_capabilities", "list_views"} else ["finance:transactions"] if item.name in {"search_transactions", "get_recurring_payments"} else ["finance:read"]
                            expected = [{"type": "oauth2", "scopes": scope}]
                            assert item.model_dump()["securitySchemes"] == expected
                            assert item.meta["securitySchemes"] == expected
                        overview = await session.call_tool("get_overview", {"query": {"start": "2026-01-01", "end": "2026-01-31"}})
                        assert not overview.isError
                        assert overview.structuredContent["items"][0]["expenses"] == "0.3"
                        assert len(overview.model_dump_json().encode()) <= tools.MAX_RESULT_BYTES
                        assert overview.meta["untrusted_fields"] == ["label", "category", "merchant"]
                        detail = await session.call_tool("search_transactions", {"query": {"start": "2026-01-01", "end": "2026-01-31", "page_size": 1}})
                        assert detail.structuredContent["total"] == 3
                        resources = await session.list_resources()
                        assert {str(item.uri) for item in resources.resources} == {"finsight://guide/financial-model", "finsight://guide/analysis-workflows", "finsight://guide/views"}
                        guide = await session.read_resource("finsight://guide/financial-model")
                        assert "decimal strings" in guide.contents[0].text
                        prompts = await session.list_prompts()
                        assert {item.name for item in prompts.prompts} == {"monthly_review", "savings_plan", "subscription_audit", "spending_change", "safe_to_spend"}
                        prompt = await session.get_prompt("safe_to_spend", {"start": "2026-01-01", "end": "2026-01-31", "currency": "EUR"})
                        assert "untrusted data" in prompt.messages[0].content.text
                        assert "at most 8 tool calls" in prompt.messages[0].content.text
            assert state["calls"] == 9
    anyio.run(run)
    assert tools.principal_context.get().owner_id == "owner-a"  # Request context reset, fixture context preserved.


def test_missing_cookie_only_invalid_scopes_revocation_and_disabled(transport_app, monkeypatch):
    app, server, state = transport_app
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    async def run():
        async with server.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000", follow_redirects=True,
                                         headers={"Accept": "application/json, text/event-stream"}) as http:
                for auth in [None, "Bearer bad", "Basic ignored", "Bearer token with spaces"]:
                    headers = {"Authorization": auth} if auth else {"Cookie": "session=browser-cookie"}
                    response = await http.post("/mcp/", json=message, headers=headers)
                    assert response.status_code == 401
                    assert "/.well-known/oauth-protected-resource/mcp" in response.headers["www-authenticate"]
                for method in [http.get, http.delete]:
                    assert (await method("/mcp/")).status_code == 401
                assert (await http.post("/mcp/", json=message, headers=authorization("no-scope"))).status_code == 403
                good = await http.post("/mcp/", json=message, headers=authorization("aggregate"))
                assert good.status_code == 200
                state["revoked"] = True
                revoked = await http.post("/mcp/", json=message, headers=authorization("aggregate"))
                assert revoked.status_code == 401
                monkeypatch.setenv("MCP_ENABLED", "false")
                assert (await http.post("/mcp/", json=message)).status_code == 404
    anyio.run(run)


def test_protocol_scope_restrictions_strict_inputs_safe_errors(transport_app, mcp_data, monkeypatch):
    app, server, _ = transport_app

    async def run():
        async with server.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers=authorization("aggregate")) as http:
                async with streamable_http_client("http://localhost:8000/mcp/", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        for name, args in [("search_transactions", {"query": {}}),
                                           ("get_accounts", {"query": {"include_names": True}}),
                                           ("get_overview", {"query": {"page_size": "10"}}),
                                           ("get_overview", {"query": {"page_size": 101}}),
                                           ("get_overview", {"query": {}, "source": "RAW PRIVATE DESCRIPTION"}),
                                           ("get_overview", {"query": {"source": "RAW PRIVATE DESCRIPTION"}})]:
                            response = await session.call_tool(name, args)
                            assert response.isError
                            assert "RAW PRIVATE DESCRIPTION" not in response.model_dump_json()
                            if name == "search_transactions" or args.get("query", {}).get("include_names"):
                                challenge = response.meta["mcp/www_authenticate"][0]
                                assert 'error="insufficient_scope"' in challenge
                                assert 'scope="finance:transactions"' in challenge
                                assert "error_description=" in challenge
                                assert 'resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource/mcp"' in challenge
                        def fail(*args):
                            raise RuntimeError("SECRET-IBAN RAW PRIVATE DESCRIPTION")
                        monkeypatch.setattr(tools, "execute_tool", fail)
                        response = await session.call_tool("get_overview", {"query": {}})
                        assert response.isError and "SECRET-IBAN" not in response.model_dump_json()
    anyio.run(run)


def test_concurrent_request_owner_context_isolation(transport_app, mcp_data):
    app, server, _ = transport_app

    async def run():
        async def call(token, expected):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers={"Authorization": f"Bearer {token}"}) as http:
                async with streamable_http_client("http://localhost:8000/mcp/", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool("get_overview", {"query": {"start": "2026-01-01", "end": "2026-01-31"}})
                        assert result.structuredContent["items"][0]["expenses"] == expected
        async with server.session_manager.run():
            async with anyio.create_task_group() as group:
                group.start_soon(call, "aggregate", "0.3")
                group.start_soon(call, "other", "777")
    anyio.run(run)


def test_main_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("MCP_ENABLED", raising=False)
    assert client.post("/mcp/").status_code == 404
    assert client.post("/mcp", follow_redirects=False).status_code == 404


def test_actual_main_exact_endpoint_has_no_redirect_and_sdk_works(mcp_data, monkeypatch):
    from app import main, mcp_server
    monkeypatch.setenv("MCP_ENABLED", "true")
    origin = main.mcp.settings.transport_security.allowed_origins[0]
    monkeypatch.setenv("APP_URL", origin)
    actor = SimpleNamespace(owner_id="owner-a", scopes=frozenset({"finance:read"}), grant_id="grant")
    def verify(token, resource):
        assert token == "synthetic" and resource == origin + "/mcp"
        return actor
    monkeypatch.setattr(mcp_server.http_app, "verifier", verify)

    async def run():
        async with main.app.router.lifespan_context(main.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=origin, follow_redirects=False) as http:
                for path in ["/mcp", "/mcp/"]:
                    for method in ["GET", "POST", "DELETE", "OPTIONS"]:
                        response = await http.request(method, path)
                        assert response.status_code == 401
                        assert "location" not in response.headers
                        assert "/.well-known/oauth-protected-resource/mcp" in response.headers["www-authenticate"]
                http.headers["Authorization"] = "Bearer synthetic"
                async with streamable_http_client(origin + "/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        assert (await session.initialize()).serverInfo.name == "FinSight"
                        result = await session.call_tool("get_overview", {"query": {"start": "2026-01-01", "end": "2026-01-31"}})
                        assert result.structuredContent["items"][0]["expenses"] == "0.3"
    anyio.run(run)


def test_transaction_only_grants_protocol_and_per_tool_step_up(transport_app, mcp_data):
    app, server, _ = transport_app

    async def run():
        async with server.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers=authorization("transactions-only")) as http:
                async with streamable_http_client("http://localhost:8000/mcp/", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        capabilities = await session.call_tool("get_capabilities", {})
                        assert capabilities.structuredContent["scopes"] == ["finance:transactions"]
                        assert not (await session.call_tool("list_views", {})).isError
                        assert (await session.list_tools()).tools
                        assert (await session.read_resource("finsight://guide/financial-model")).contents
                        assert (await session.get_prompt("monthly_review", {"start": "2026-01-01", "end": "2026-01-31"})).messages
                        detail = await session.call_tool("search_transactions", {"query": {"start": "2026-01-01", "end": "2026-01-31"}})
                        assert not detail.isError and detail.structuredContent["total"] == 3
                        assert not (await session.call_tool("get_recurring_payments", {"query": {}})).isError
                        aggregate = await session.call_tool("get_overview", {"query": {}})
                        assert aggregate.isError
                        assert 'scope="finance:read"' in aggregate.meta["mcp/www_authenticate"][0]
    anyio.run(run)


def test_production_host_validation_is_exact_app_authority(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://finance.example.test:9443")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MCP_ENABLED", "true")
    server = create_server()
    assert server.settings.transport_security.allowed_hosts == ["finance.example.test:9443"]
    app = FastAPI()
    actor = SimpleNamespace(owner_id="owner-a", scopes=frozenset({"finance:read"}), grant_id="grant")
    app.mount("/mcp", BearerMiddleware(server.streamable_http_app(), verifier=lambda *_: actor))

    async def run():
        async with server.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://finance.example.test:9443",
                                         headers={**authorization("synthetic"), "Accept": "application/json, text/event-stream"}) as http:
                message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
                assert (await http.post("/mcp/", json=message)).status_code == 200
                for host in ["localhost", "testserver", "finance.example.test", "finance.example.test:1234", "attacker.example"]:
                    assert (await http.post("/mcp/", json=message, headers={"Host": host})).status_code in {400, 421}
                assert (await http.post("/mcp/", json=message, headers={"Origin": "https://attacker.example"})).status_code == 403
    anyio.run(run)
