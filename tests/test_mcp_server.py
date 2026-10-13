"""The MCP server: JSON-RPC 2.0 handling and the five read-only tools, offline against the NHANES fixture."""
import json
from pathlib import Path

import pytest

import sdcreader.mcp_server as srv
from sdcreader.mcp_server import TOOLS, TOOL_HANDLERS, _handle_request

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "nhanes-participant"
CT = "xy8upneajsb8vdcmnve01g6g"


def rpc(method, params=None, id=1):
    req = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        req["params"] = params
    return _handle_request(req)


def call(name, arguments):
    resp = rpc("tools/call", {"name": name, "arguments": arguments})
    assert "result" in resp, resp
    content = resp["result"]["content"]
    assert len(content) == 1 and content[0]["type"] == "text"
    return resp["result"], content[0]["text"]


def call_ok(name, arguments):
    result, text = call(name, arguments)
    assert not result.get("isError"), text
    return json.loads(text)


def call_err(name, arguments):
    result, text = call(name, arguments)
    assert result.get("isError") is True, text
    return text


@pytest.fixture(autouse=True)
def clear_cache():
    srv._CACHE.clear()
    yield
    srv._CACHE.clear()


class TestProtocol:
    def test_initialize_negotiates_a_supported_revision(self):
        r = rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]
        assert r["protocolVersion"] == "2025-06-18"
        assert r["serverInfo"]["name"] == "sdcreader"
        assert "tools" in r["capabilities"]
        assert "No tool takes a URL" in r["instructions"]

    def test_initialize_answers_newest_for_an_unknown_revision(self):
        r = rpc("initialize", {"protocolVersion": "2024-11-05"})["result"]
        assert r["protocolVersion"] == srv.MCP_PROTOCOL_VERSION

    def test_initialized_notification_has_no_response(self):
        assert _handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    def test_tools_list_names_the_five_tools_with_schemas(self):
        tools = rpc("tools/list", {})["result"]["tools"]
        assert {t["name"] for t in tools} == {"find_models", "describe_model", "list_leaves", "list_codes", "check_package"}
        assert set(TOOL_HANDLERS) == {t["name"] for t in TOOLS}
        for t in tools:
            assert t["inputSchema"]["type"] == "object"
            assert t["description"]

    def test_unknown_tool_and_method_are_protocol_errors(self):
        assert rpc("tools/call", {"name": "nope", "arguments": {}})["error"]["code"] == -32601
        assert rpc("no/such", {})["error"]["code"] == -32601
        assert _handle_request({"jsonrpc": "2.0", "method": "no/such"}) is None

    def test_non_object_request_and_params_are_invalid_requests(self):
        assert _handle_request(["not", "an", "object"])["error"]["code"] == -32600
        assert rpc("tools/list", "x")["error"]["code"] == -32600
        assert rpc("tools/call", {"name": "describe_model", "arguments": "x"})["error"]["code"] == -32602

    def test_ping(self):
        assert rpc("ping", {})["result"] == {}


class TestTools:
    def test_describe_model_from_a_directory(self):
        d = call_ok("describe_model", {"directory": str(SAMPLE)})
        assert d["ct_id"] == CT
        assert d["title"] == "NHANES Participant"
        assert d["leaves"] == 153 and d["components"] > d["leaves"]
        assert d["schema_url_pinned"].startswith(f"https://sdcstudio.axius-sdc.com/dmlib/dm-{CT}.xsd?sha256=")
        assert d["schema_is_current"] is True
        assert sum(d["leaves_by_type"].values()) == 153
        assert d["root"]["ct_id"] and d["root"]["label"]
        # defaults are null, never facts
        assert d["dublin_core"]["coverage"] is None or d["dublin_core"]["coverage"] != "Universal"
        assert d["dublin_core"]["relation"] is None or d["dublin_core"]["relation"] != "None"

    def test_list_leaves_pages_in_document_order(self):
        first = call_ok("list_leaves", {"directory": str(SAMPLE), "limit": 10})
        assert first["total"] == 153 and first["returned"] == 10 and first["next_offset"] == 10
        assert [l["position"] for l in first["leaves"]] == list(range(10))
        last = call_ok("list_leaves", {"directory": str(SAMPLE), "offset": 150, "limit": 10})
        assert last["returned"] == 3 and last["next_offset"] is None
        leaf = first["leaves"][0]
        from sdcreader import LEAF_TYPES
        assert leaf["slug"] and leaf["path"] and leaf["sdc_type"] in LEAF_TYPES
        assert isinstance(leaf["codes"], int) and isinstance(leaf["links"], dict)

    def test_list_codes_for_an_enumerated_component(self):
        leaves = call_ok("list_leaves", {"directory": str(SAMPLE), "limit": 200})["leaves"]
        coded = next(l for l in leaves if l["codes"] > 0)
        c = call_ok("list_codes", {"directory": str(SAMPLE), "component": coded["ct_id"]})
        assert c["count"] == coded["codes"] and c["component"]["ct_id"] == coded["ct_id"]
        assert all(k["value"] and k["iri"].startswith("http") for k in c["codes"])

    def test_list_codes_unknown_component_is_a_tool_error(self):
        text = call_err("list_codes", {"directory": str(SAMPLE), "component": "nope"})
        assert "No component" in text

    def test_source_argument_rules(self):
        assert "exactly one" in call_err("describe_model", {})
        assert "exactly one" in call_err("describe_model", {"ct_id": CT, "directory": str(SAMPLE)})
        assert "integer" in call_err("list_leaves", {"directory": str(SAMPLE), "limit": "ten"})
        assert "between" in call_err("list_leaves", {"directory": str(SAMPLE), "limit": 10_000})

    def test_check_package_ok_and_refusals(self, tmp_path):
        ok = call_ok("check_package", {"directory": str(SAMPLE)})
        assert ok["ok"] is True and ok["ct_id"] == CT and ok["versions_present"] is True
        bad = call_ok("check_package", {"directory": str(tmp_path)})
        assert bad["ok"] is False and "expected one dm-<ct>.xsd" in bad["error"]

    def test_a_package_is_read_once_per_process(self):
        call_ok("describe_model", {"directory": str(SAMPLE)})
        call_ok("list_leaves", {"directory": str(SAMPLE)})
        assert len(srv._CACHE) == 1

    def test_find_models_queries_the_fixed_host(self, monkeypatch):
        import requests

        seen = {}

        class R:
            status_code = 200

            def json(self):
                return {"count": 1, "results": [{"ct_id": CT, "title": "NHANES Participant", "project_name": "FAIR Data Demo", "description": "x", "updated": "2026-01-01"}]}

        def fake_get(url, params=None, timeout=None):
            seen["url"], seen["params"] = url, params
            return R()

        monkeypatch.setattr(requests, "get", fake_get)
        r = call_ok("find_models", {"search": "NHANES", "project": "FAIR Data Demo", "page_size": 5})
        assert seen["url"] == f"{srv._HOST}/api/v1/catalog/dms/"
        assert seen["params"]["search"] == "NHANES" and seen["params"]["project"] == "FAIR Data Demo" and seen["params"]["page_size"] == 5
        assert r["count"] == 1 and r["models"][0]["ct_id"] == CT and r["models"][0]["project"] == "FAIR Data Demo"

    def test_describe_model_by_ct_id_uses_fetch_package(self, monkeypatch):
        from sdcreader import package as pkgmod

        calls = []

        def fake_fetch(ct_id, host=None, **kw):
            calls.append((ct_id, host))
            return pkgmod.load_package(SAMPLE, host=host)

        monkeypatch.setattr(srv, "fetch_package", fake_fetch)
        d = call_ok("describe_model", {"ct_id": CT})
        assert d["ct_id"] == CT and calls == [(CT, srv._HOST)]


@pytest.mark.network
def test_find_models_against_production():
    r = call_ok("find_models", {"project": "FAIR Data Demo", "page_size": 3})
    assert r["count"] >= 1 and r["models"][0]["project"] == "FAIR Data Demo"
