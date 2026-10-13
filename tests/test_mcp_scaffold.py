"""The shared MCP scaffold in sdcreader.mcp: protocol handling, tool errors, and the package cache."""
from pathlib import Path

import pytest

from sdcreader.mcp import PackageCache, Server, ToolError, int_arg, source_properties, str_arg

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "nhanes-participant"
CT = "xy8upneajsb8vdcmnve01g6g"


def make():
    tools = [{"name": "echo", "description": "echo", "inputSchema": {"type": "object"}},
             {"name": "boom", "description": "boom", "inputSchema": {"type": "object"}},
             {"name": "defect", "description": "defect", "inputSchema": {"type": "object"}}]
    handlers = {"echo": lambda a: {"got": a}, "boom": lambda a: (_ for _ in ()).throw(ToolError("bad input")),
                "defect": lambda a: 1 / 0}
    return Server("t", "0.0", "do things", tools, handlers, "https://example.org/issues")


def test_a_server_needs_a_handler_per_tool_and_vice_versa():
    with pytest.raises(ValueError):
        Server("t", "0", "i", [{"name": "a", "description": "", "inputSchema": {}}], {}, "u")


def test_initialize_negotiates_and_lists_tools():
    s = make()
    r = s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})["result"]
    assert r["protocolVersion"] == "2025-06-18" and r["serverInfo"] == {"name": "t", "version": "0.0"} and r["instructions"] == "do things"
    r = s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})["result"]
    assert r["protocolVersion"] == "2025-11-25"
    assert [t["name"] for t in s.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]] == ["echo", "boom", "defect"]
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert s.handle({"jsonrpc": "2.0", "id": 3, "method": "ping"})["result"] == {}


def test_tool_results_errors_and_defects():
    s = make()
    call = lambda n, a: s.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": n, "arguments": a}})["result"]
    ok = call("echo", {"x": 1})
    assert "isError" not in ok and ok["content"][0]["text"] == '{"got": {"x": 1}}'
    bad = call("boom", {})
    assert bad["isError"] is True and "bad input" in bad["content"][0]["text"]
    defect = call("defect", {})
    assert defect["isError"] is True and "ZeroDivisionError" in defect["content"][0]["text"] and "example.org/issues" in defect["content"][0]["text"]
    assert "Traceback" not in defect["content"][0]["text"]


def test_request_guards():
    s = make()
    assert s.handle(["x"])["error"]["code"] == -32600
    assert s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": "x"})["error"]["code"] == -32600
    assert s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "echo", "arguments": []}})["error"]["code"] == -32602
    assert s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "nope"}})["error"]["code"] == -32601
    assert s.handle({"jsonrpc": "2.0", "id": 1, "method": "no/such"})["error"]["code"] == -32601
    assert s.handle({"jsonrpc": "2.0", "method": "no/such"}) is None


def test_package_cache_reads_once_and_resolves_singular_and_plural():
    seen = []
    cache = PackageCache(host="https://h.example", loader=lambda d, h: seen.append(d) or __import__("sdcreader").load_package(d, host=h))
    pkg, model = cache.one({"directory": str(SAMPLE)})
    assert model.ct_id == CT and pkg.host == "https://h.example"
    cache.one({"directory": str(SAMPLE)})
    assert len(seen) == 1 and len(cache.storage) == 1
    both = cache.many({"directories": [str(SAMPLE)]})
    assert len(both) == 1 and both[0][1].ct_id == CT
    with pytest.raises(ToolError):
        cache.one({})
    with pytest.raises(ToolError):
        cache.one({"ct_id": CT, "directory": str(SAMPLE)})
    with pytest.raises(ToolError):
        cache.many({})
    with pytest.raises(ToolError):
        cache.many({"ct_ids": "x"})


def test_argument_helpers_and_source_schemas():
    assert int_arg({"n": 3}, "n", 1, 1, 5) == 3 and int_arg({}, "n", 1, 1, 5) == 1
    for bad in ({"n": "3"}, {"n": True}, {"n": 9}):
        with pytest.raises(ToolError):
            int_arg(bad, "n", 1, 1, 5)
    assert str_arg({"s": "x"}, "s") == "x" and str_arg({}, "s") is None
    with pytest.raises(ToolError):
        str_arg({}, "s", required=True)
    with pytest.raises(ToolError):
        str_arg({"s": 1}, "s")
    assert set(source_properties()) == {"ct_id", "directory"} and set(source_properties(plural=True)) == {"ct_ids", "directories"}
