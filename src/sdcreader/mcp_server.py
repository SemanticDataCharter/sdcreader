#
# Copyright (c) 2026, Axius SDC, Inc.
# Licensed under the Apache License, Version 2.0.
#
"""
MCP stdio server for `sdcreader`.

`sdcvalidator`, `sdcgovernance` and `sdcreceipt` are registered MCP servers, so
an agent can validate a record, evaluate governance over it and settle it. It
could not read the model those acts are about. This closes that gap: find a
published model in the public catalog, read its record structure, its
enumerated values with their codes and definitions, its Dublin Core as the
modeler wrote it, and the pinned schema URL, with no account anywhere.

**Five tools, read-only.** `find_models` searches the public catalog.
`describe_model` summarizes one model. `list_leaves` walks its leaves in
document order, paged, because a model can have more than a thousand.
`list_codes` gives one component's enumerated values. `check_package` runs the
reader's integrity check on a package directory.

**No tool takes a URL.** The catalog host is fixed when the server starts
(`--host`, default SDCStudio's public catalog), so a caller cannot point this
server at an arbitrary host. A tool takes either a model identifier, fetched
from that host, or a package directory already on disk.

**A default is never reported as a fact.** Dublin Core comes through
`Model.dc()`, so SDCStudio's field defaults ("Universal" coverage, "None"
relation) come back as null rather than as what the modeler said.

Reuse, do not reimplement: every tool calls the same functions the library
exposes. If the two interfaces ever describe one model differently, the
product is broken.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from sdcreader import __version__
from sdcreader.model import EXACT, IDENTIFIER, PUBLISHER, SEE_ALSO, SOURCE, Model, read_model
from sdcreader.package import DEFAULT_HOST, ModelPackage, PackageError, fetch_package, load_package

JSONRPC_VERSION = "2.0"

#: Newest revision this server implements. `initialize` negotiates rather than
#: asserting, so a client on an older supported revision is honoured. The
#: 2026-07-28 revision removes the initialize handshake and is not claimed.
MCP_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-11-25")

SERVER_NAME = "sdcreader"
SERVER_VERSION = __version__

#: Set once by `main()`, never from tool arguments.
_HOST: str = DEFAULT_HOST

#: Packages fetched or loaded in this process, by model identifier. A model's
#: package is immutable once published, so caching it for the life of the
#: server is safe and keeps a paged walk from re-fetching four files per page.
_CACHE: dict[str, tuple[ModelPackage, Model]] = {}

DEFAULT_PAGE = 50
MAX_PAGE = 200
DEFAULT_FIND = 20
MAX_FIND = 100


class ReaderToolError(Exception):
    """A tool failure the calling model can act on: bad input, or a package that does not hold up."""


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

TOOLS = [
    {
        "name": "find_models",
        "description": (
            "Search SDCStudio's public catalog of published models by text, or list "
            "the models of one public project by name. Needs no account. Returns "
            "identifiers, titles and projects; pass an identifier to describe_model."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Text matched against title and description."},
                "project": {"type": "string", "description": "A public project's exact name, for example NIH_CDE."},
                "page": {"type": "integer", "minimum": 1, "default": 1},
                "page_size": {"type": "integer", "minimum": 1, "maximum": MAX_FIND, "default": DEFAULT_FIND},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "describe_model",
        "description": (
            "Describe one published model: title, description, project, the root "
            "record, how many leaves and components it has and of which types, its "
            "Dublin Core as the modeler wrote it (defaults reported as null), its "
            "semantic links, and the schema URL pinned to the SHA-256 of the bytes "
            "every record is validated against."
        ),
        "inputSchema": {"type": "object", "properties": dict(SOURCE_ARGS), "additionalProperties": False},
    },
    {
        "name": "list_leaves",
        "description": (
            "The model's leaves in document order, each with its path of clusters, "
            "its SDC4 type, its constraints, how many enumerated values it has and "
            "its identity links. Paged: a model can have more than a thousand leaves."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **SOURCE_ARGS,
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE, "default": DEFAULT_PAGE},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_codes",
        "description": (
            "The enumerated values of one component in a model: each value with the "
            "IRI, definition and code system the published schema annotates it with."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **SOURCE_ARGS,
                "component": {"type": "string", "description": "The component's identifier (ct_id), as list_leaves reports it."},
            },
            "required": ["component"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_package",
        "description": (
            "Run the reader's integrity check on a package directory: the JSON-LD "
            "names the directory's model, it has components, the schema is an XML "
            "Schema, and its bytes are the published current version when "
            "versions.json is present. Returns the SHA-256 and the pinned schema URL."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"directory": SOURCE_ARGS["directory"]},
            "required": ["directory"],
            "additionalProperties": False,
        },
    },
]


def _package(args: dict[str, Any]) -> tuple[ModelPackage, Model]:
    ct_id = args.get("ct_id")
    directory = args.get("directory")
    if bool(ct_id) == bool(directory):
        raise ReaderToolError("Give exactly one of `ct_id` (fetched from the catalog) or `directory` (a package on disk).")
    if ct_id is not None and not isinstance(ct_id, str):
        raise ReaderToolError("`ct_id` must be a string.")
    if directory is not None and not isinstance(directory, str):
        raise ReaderToolError("`directory` must be a string path.")
    key = ct_id or f"dir:{Path(directory).resolve()}"
    if key in _CACHE:
        return _CACHE[key]
    try:
        pkg = fetch_package(ct_id, host=_HOST) if ct_id else load_package(directory, host=_HOST)
        model = read_model(pkg)
    except PackageError as exc:
        raise ReaderToolError(str(exc)) from exc
    except OSError as exc:
        raise ReaderToolError(f"Could not read the package: {exc}") from exc
    _CACHE[key] = (pkg, model)
    return pkg, model


def _int(args: dict[str, Any], name: str, default: int, lo: int, hi: int) -> int:
    v = args.get(name, default)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ReaderToolError(f"`{name}` must be an integer.")
    if v < lo or v > hi:
        raise ReaderToolError(f"`{name}` must be between {lo} and {hi}.")
    return v


def _links(component) -> dict[str, list[str]]:
    """The component's semantic links by short predicate name, only those present."""
    names = {IDENTIFIER: "identifier", SOURCE: "source", PUBLISHER: "publisher", EXACT: "exactMatch", SEE_ALSO: "seeAlso"}
    out = {}
    for pred, short in names.items():
        if component.links.get(pred):
            out[short] = list(component.links[pred])
    return out


def _handle_find_models(args: dict[str, Any]) -> Any:
    import requests  # a base dependency since 4.1.0, so the registry's `uvx sdcreader` can search

    search = args.get("search", "")
    project = args.get("project", "")
    if not isinstance(search, str) or not isinstance(project, str):
        raise ReaderToolError("`search` and `project` must be strings.")
    page = _int(args, "page", 1, 1, 10_000)
    page_size = _int(args, "page_size", DEFAULT_FIND, 1, MAX_FIND)
    params = {"format": "json", "page": page, "page_size": page_size}
    if search:
        params["search"] = search
    if project:
        params["project"] = project
    try:
        r = requests.get(f"{_HOST}/api/v1/catalog/dms/", params=params, timeout=60)
    except requests.RequestException as exc:
        raise ReaderToolError(f"The catalog could not be reached: {exc}") from exc
    if r.status_code != 200:
        raise ReaderToolError(f"The catalog answered HTTP {r.status_code}.")
    data = r.json()
    results = [
        {
            "ct_id": m.get("ct_id"),
            "title": m.get("title"),
            "project": m.get("project_name"),
            "description": (m.get("description") or "")[:300],
            "updated": m.get("updated"),
        }
        for m in data.get("results", [])
    ]
    return {
        "host": _HOST,
        "count": data.get("count"),
        "page": page,
        "page_size": page_size,
        "models": results,
        "hint": "Pass a ct_id to describe_model. Models are listed only from public projects.",
    }


def _handle_describe_model(args: dict[str, Any]) -> Any:
    pkg, model = _package(args)
    by_type: dict[str, int] = {}
    for leaf in model.leaves:
        by_type[leaf.component.sdc_type] = by_type.get(leaf.component.sdc_type, 0) + 1
    dc_names = ("creator", "publisher", "date", "language", "coverage", "relation", "source", "type", "format", "identifier")
    dublin_core = {name: model.dc(name) for name in dc_names}
    dublin_core["contributors"] = model.contributors
    dublin_core["subjects"] = model.subjects
    dublin_core["rights_url"] = model.rights_url or None
    dublin_core["rights_statement"] = model.rights_statement or None
    return {
        "ct_id": model.ct_id,
        "title": model.title,
        "description": model.description,
        "project": pkg.catalog.get("project_name"),
        "catalog_url": pkg.catalog_url,
        "schema_url": pkg.schema_url,
        "schema_sha256": pkg.sha256,
        "schema_url_pinned": pkg.schema_url_pinned,
        "schema_is_current": (pkg.versions.get("current_sha256") in (None, pkg.sha256)),
        "root": {"ct_id": model.root.ct_id, "label": model.root.label, "description": model.root.description, "links": _links(model.root)},
        "components": len(model.components),
        "leaves": len(model.leaves),
        "leaves_by_type": dict(sorted(by_type.items())),
        "enumerated_components": sum(1 for v in model.codes.values() if v),
        "dublin_core": dublin_core,
        "hint": "Dublin Core values are what the modeler wrote; SDCStudio's defaults are reported as null, never as facts.",
    }


def _handle_list_leaves(args: dict[str, Any]) -> Any:
    pkg, model = _package(args)
    offset = _int(args, "offset", 0, 0, 10_000_000)
    limit = _int(args, "limit", DEFAULT_PAGE, 1, MAX_PAGE)
    page = model.leaves[offset : offset + limit]
    leaves = []
    for leaf in page:
        c = leaf.component
        leaves.append(
            {
                "position": leaf.position,
                "slug": leaf.slug,
                "ct_id": c.ct_id,
                "label": c.label,
                "sdc_type": c.sdc_type,
                "data_type": c.data_type,
                "path": [p.label for p in leaf.path],
                "description": c.description,
                "constraints": c.constraints,
                "codes": len(model.codes.get(c.ct_id, [])),
                "links": _links(c),
            }
        )
    return {
        "ct_id": model.ct_id,
        "title": model.title,
        "total": len(model.leaves),
        "offset": offset,
        "limit": limit,
        "returned": len(leaves),
        "next_offset": offset + limit if offset + limit < len(model.leaves) else None,
        "leaves": leaves,
    }


def _handle_list_codes(args: dict[str, Any]) -> Any:
    pkg, model = _package(args)
    comp_id = args.get("component")
    if not isinstance(comp_id, str) or not comp_id:
        raise ReaderToolError("`component` must be a component identifier (ct_id).")
    comp = model.components.get(comp_id)
    if comp is None:
        raise ReaderToolError(f"No component {comp_id!r} in model {model.ct_id}. list_leaves reports the identifiers.")
    codes = model.codes.get(comp_id, [])
    return {
        "ct_id": model.ct_id,
        "component": {"ct_id": comp.ct_id, "label": comp.label, "sdc_type": comp.sdc_type, "links": _links(comp)},
        "count": len(codes),
        "codes": [{"value": k.value, "iri": k.iri, "definition": k.definition, "defined_by": k.defined_by} for k in codes],
        "hint": None if codes else "This component has no enumerated values in the published schema.",
    }


def _handle_check_package(args: dict[str, Any]) -> Any:
    directory = args.get("directory")
    if not isinstance(directory, str) or not directory:
        raise ReaderToolError("`directory` must be a string path.")
    try:
        pkg = load_package(directory, host=_HOST)
    except PackageError as exc:
        return {"ok": False, "directory": directory, "error": str(exc)}
    except OSError as exc:
        raise ReaderToolError(f"Could not read the package: {exc}") from exc
    return {
        "ok": True,
        "directory": directory,
        "ct_id": pkg.ct_id,
        "schema_sha256": pkg.sha256,
        "schema_url_pinned": pkg.schema_url_pinned,
        "published_current_sha256": pkg.versions.get("current_sha256"),
        "versions_present": bool(pkg.versions),
        "catalog_present": bool(pkg.catalog),
    }


TOOL_HANDLERS = {
    "find_models": _handle_find_models,
    "describe_model": _handle_describe_model,
    "list_leaves": _handle_list_leaves,
    "list_codes": _handle_list_codes,
    "check_package": _handle_check_package,
}


def _jsonrpc_response(id: Any, result: Any) -> dict:
    return {"jsonrpc": JSONRPC_VERSION, "id": id, "result": result}


def _jsonrpc_error(id: Any, code: int, message: str, data: Any = None) -> dict:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": id, "error": error}


def _handle_request(request: Any) -> dict | None:
    """Handle one JSON-RPC 2.0 request. Returns a response, or None for a notification."""
    if not isinstance(request, dict):
        return _jsonrpc_error(None, -32600, "Invalid request: expected a JSON object.")
    method = request.get("method", "")
    params = request.get("params", {})
    req_id = request.get("id")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _jsonrpc_error(req_id, -32600, "Invalid request: `params` must be an object.")

    if method == "initialize":
        requested = params.get("protocolVersion")
        negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
        return _jsonrpc_response(
            req_id,
            {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Read published Semantic Data Charter models. `find_models` searches "
                    f"the public catalog at {_HOST}; `describe_model`, `list_leaves` and "
                    "`list_codes` read one model by its ct_id from that host or from a "
                    "package directory on disk; `check_package` verifies a directory. "
                    "All tools are read-only and need no account. No tool takes a URL."
                ),
            },
        )

    elif method == "notifications/initialized":
        return None

    elif method == "tools/list":
        return _jsonrpc_response(req_id, {"tools": TOOLS})

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        if tool_args is None:
            tool_args = {}
        if not isinstance(tool_args, dict):
            return _jsonrpc_error(req_id, -32602, "Invalid params: `arguments` must be an object.")
        handler = TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return _jsonrpc_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = handler(tool_args)
            return _jsonrpc_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, default=str)}]})
        except ReaderToolError as exc:
            # SEP-1303: a failure the model can correct is a tool error in the
            # result, not a protocol error it would never see.
            return _jsonrpc_response(req_id, {"content": [{"type": "text", "text": f"Tool execution error: {exc}"}], "isError": True})
        except Exception as exc:
            return _jsonrpc_response(
                req_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Tool execution error: the server could not process this input "
                                f"({type(exc).__name__}). This is a defect worth reporting at "
                                "https://github.com/SemanticDataCharter/sdcreader/issues"
                            ),
                        }
                    ],
                    "isError": True,
                },
            )

    elif method == "ping":
        return _jsonrpc_response(req_id, {})

    else:
        if req_id is not None:
            return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")
        return None


def run_stdio() -> None:
    """One JSON-RPC message per line on stdin, one response per line on stdout. stdio and no SDK."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps(_jsonrpc_error(None, -32700, f"Parse error: {exc}")) + "\n")
            sys.stdout.flush()
            continue
        response = _handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def main(argv: list[str] | None = None) -> None:
    """Entry point for `sdcreader` and `sdcreader-mcp`."""
    import argparse

    global _HOST

    parser = argparse.ArgumentParser(prog="sdcreader-mcp", description="MCP stdio server for reading published Semantic Data Charter models.")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=(
            "The SDCStudio host whose public catalog is read, fixed here so a caller "
            f"cannot redirect the server. Default {DEFAULT_HOST}."
        ),
    )
    args = parser.parse_args(argv)
    _HOST = args.host.rstrip("/")
    run_stdio()


if __name__ == "__main__":
    main()
