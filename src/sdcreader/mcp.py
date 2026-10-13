#
# Copyright (c) 2026, Axius SDC, Inc.
# Licensed under the Apache License, Version 2.0.
#
"""
The MCP scaffold the SDC servers share: JSON-RPC 2.0 over stdio, one message
per line, no SDK.

`sdcvalidator`, `sdcgovernance`, `sdcreceipt` and `sdcreader` each carried this
by hand. The four projection servers would have made eight copies, so it lives
here once, as the reader itself does: `sdcreader` is the package every
projection already depends on.

What a server built on this gets, and must not re-implement:

- `initialize` that negotiates rather than asserts: a client asking for a
  revision in `SUPPORTED_PROTOCOL_VERSIONS` gets it echoed; anything else gets
  the newest and decides for itself. 2026-07-28 removes the initialize
  handshake and is a different architecture, so it is not claimed.
- Tool failures as `isError` results (SEP-1303), never JSON-RPC errors, so the
  calling model sees what went wrong and can correct itself. A `ToolError`
  is the recoverable kind and travels with its message; anything else is a
  defect and travels without its traceback.
- `-32600` for a request or `params` that is not an object, `-32602` for
  `arguments` that is not an object, `-32601` for an unknown method or tool,
  `-32700` for a line that is not JSON.
- `PackageCache`: the `ct_id`-or-`directory` source argument every reader-based
  tool takes, resolved once per process. A published package is immutable, so
  caching it for the life of the server is safe.

No tool built on this may take a URL as an argument. The catalog host is fixed
when the server starts, so a caller cannot point a server at an arbitrary host.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from sdcreader.model import Model, read_model
from sdcreader.package import DEFAULT_HOST, ModelPackage, PackageError, fetch_package, load_package

JSONRPC_VERSION = "2.0"

#: Newest revision this scaffold implements, and the set it negotiates.
MCP_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-11-25")

__all__ = [
    "JSONRPC_VERSION", "MCP_PROTOCOL_VERSION", "SUPPORTED_PROTOCOL_VERSIONS",
    "ToolError", "Server", "PackageCache", "SOURCE_ARGS", "source_properties", "int_arg", "str_arg",
]


class ToolError(Exception):
    """A tool failure the calling model can act on: bad input, or a package that does not hold up."""


#: The source argument every reader-based tool takes: one model by identifier (fetched from the fixed host) or one
#: package directory on disk, never both.
SOURCE_ARGS = {
    "ct_id": {
        "type": "string",
        "description": "The model's identifier (CUID2) in the public catalog; the package is fetched from the host this server was started with.",
    },
    "directory": {
        "type": "string",
        "description": "A package directory already on disk (dm-<ct>.jsonld and dm-<ct>.xsd, optionally catalog.json and versions.json). Give this or ct_id, not both.",
    },
}


def source_properties(plural: bool = False) -> dict:
    """The JSON Schema properties for the source argument; `plural` gives the list forms a multi-model catalog takes."""
    if not plural:
        return dict(SOURCE_ARGS)
    return {
        "ct_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                   "description": "Model identifiers (CUID2) in the public catalog, fetched from the host this server was started with."},
        "directories": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                        "description": "Package directories on disk. Give ct_ids or directories or both; at least one model."},
    }


def int_arg(args: dict[str, Any], name: str, default: int, lo: int, hi: int) -> int:
    v = args.get(name, default)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ToolError(f"`{name}` must be an integer.")
    if v < lo or v > hi:
        raise ToolError(f"`{name}` must be between {lo} and {hi}.")
    return v


def str_arg(args: dict[str, Any], name: str, default: str | None = None, required: bool = False) -> str | None:
    v = args.get(name, default)
    if v is None:
        if required:
            raise ToolError(f"`{name}` is required.")
        return None
    if not isinstance(v, str):
        raise ToolError(f"`{name}` must be a string.")
    return v


class PackageCache:
    """Packages fetched or loaded in this process, by source, read once."""

    def __init__(self, host: str = DEFAULT_HOST, storage: dict | None = None, fetcher: Callable | None = None, loader: Callable | None = None):
        self.host = host.rstrip("/")
        self.storage: dict[str, tuple[ModelPackage, Model]] = storage if storage is not None else {}
        # Injectable so a server module can expose `fetch_package` as its own patchable name for tests.
        self.fetcher = fetcher or (lambda ct_id, host: fetch_package(ct_id, host=host))
        self.loader = loader or (lambda directory, host: load_package(directory, host=host))

    def get(self, ct_id: str | None = None, directory: str | None = None) -> tuple[ModelPackage, Model]:
        if bool(ct_id) == bool(directory):
            raise ToolError("Give exactly one of `ct_id` (fetched from the catalog) or `directory` (a package on disk).")
        if ct_id is not None and not isinstance(ct_id, str):
            raise ToolError("`ct_id` must be a string.")
        if directory is not None and not isinstance(directory, str):
            raise ToolError("`directory` must be a string path.")
        key = ct_id or f"dir:{Path(directory).resolve()}"
        if key in self.storage:
            return self.storage[key]
        try:
            pkg = self.fetcher(ct_id, self.host) if ct_id else self.loader(directory, self.host)
            model = read_model(pkg)
        except PackageError as exc:
            raise ToolError(str(exc)) from exc
        except OSError as exc:
            raise ToolError(f"Could not read the package: {exc}") from exc
        self.storage[key] = (pkg, model)
        return pkg, model

    def one(self, args: dict[str, Any]) -> tuple[ModelPackage, Model]:
        """The single source a tool's arguments name."""
        return self.get(args.get("ct_id"), args.get("directory"))

    def many(self, args: dict[str, Any]) -> list[tuple[ModelPackage, Model]]:
        """Every source a multi-model tool's arguments name, in the order given, identifiers first."""
        ct_ids = args.get("ct_ids") or []
        dirs = args.get("directories") or []
        if not isinstance(ct_ids, list) or not isinstance(dirs, list) or not all(isinstance(x, str) for x in ct_ids + dirs):
            raise ToolError("`ct_ids` and `directories` must be arrays of strings.")
        if not ct_ids and not dirs:
            raise ToolError("Give at least one model in `ct_ids` or `directories`.")
        return [self.get(ct_id=c) for c in ct_ids] + [self.get(directory=d) for d in dirs]


class Server:
    """One MCP server: a name, a version, its instructions, its tools and their handlers."""

    def __init__(self, name: str, version: str, instructions: str, tools: list[dict],
                 handlers: dict[str, Callable[[dict[str, Any]], Any]], issues_url: str):
        if set(handlers) != {t["name"] for t in tools}:
            raise ValueError("every tool needs a handler and every handler a tool")
        self.name, self.version, self.instructions = name, version, instructions
        self.tools, self.handlers, self.issues_url = tools, handlers, issues_url

    @staticmethod
    def _response(id: Any, result: Any) -> dict:
        return {"jsonrpc": JSONRPC_VERSION, "id": id, "result": result}

    @staticmethod
    def _error(id: Any, code: int, message: str, data: Any = None) -> dict:
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": JSONRPC_VERSION, "id": id, "error": error}

    def _tool_error(self, id: Any, text: str) -> dict:
        return self._response(id, {"content": [{"type": "text", "text": text}], "isError": True})

    def handle(self, request: Any) -> dict | None:
        """Handle one JSON-RPC 2.0 request. Returns a response, or None for a notification."""
        if not isinstance(request, dict):
            return self._error(None, -32600, "Invalid request: expected a JSON object.")
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return self._error(req_id, -32600, "Invalid request: `params` must be an object.")

        if method == "initialize":
            requested = params.get("protocolVersion")
            negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
            return self._response(req_id, {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": self.name, "version": self.version},
                "instructions": self.instructions,
            })
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return self._response(req_id, {"tools": self.tools})
        if method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            if tool_args is None:
                tool_args = {}
            if not isinstance(tool_args, dict):
                return self._error(req_id, -32602, "Invalid params: `arguments` must be an object.")
            handler = self.handlers.get(tool_name)
            if handler is None:
                return self._error(req_id, -32601, f"Unknown tool: {tool_name}")
            try:
                result = handler(tool_args)
            except ToolError as exc:
                return self._tool_error(req_id, f"Tool execution error: {exc}")
            except Exception as exc:  # a defect in the server, reported without its traceback
                return self._tool_error(req_id, (
                    f"Tool execution error: the server could not process this input ({type(exc).__name__}). "
                    f"This is a defect worth reporting at {self.issues_url}"))
            if isinstance(result, str):
                text = result
            else:
                text = json.dumps(result, default=str)
            return self._response(req_id, {"content": [{"type": "text", "text": text}]})
        if method == "ping":
            return self._response(req_id, {})
        if req_id is not None:
            return self._error(req_id, -32601, f"Method not found: {method}")
        return None

    def run_stdio(self) -> None:
        """One JSON-RPC message per line on stdin, one response per line on stdout."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                sys.stdout.write(json.dumps(self._error(None, -32700, f"Parse error: {exc}")) + "\n")
                sys.stdout.flush()
                continue
            response = self.handle(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
