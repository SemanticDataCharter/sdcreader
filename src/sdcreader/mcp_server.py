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

**Six tools, read-only.** `find_models` searches the public catalog.
`describe_model` summarizes one model. `list_leaves` walks its leaves in
document order, paged, because a model can have more than a thousand.
`list_codes` gives one component's enumerated values. `check_package` runs the
reader's integrity check on a package directory. `read_record` (4.3.0) reads a
Governed Data Record on disk against its model: the record's attributes and
each value with its component, paged, Exceptional Values included.

**No tool takes a URL.** The catalog host is fixed when the server starts
(`--host`, default SDCStudio's public catalog), so a caller cannot point this
server at an arbitrary host. A tool takes either a model identifier, fetched
from that host, or a package directory already on disk.

**A default is never reported as a fact.** Dublin Core comes through
`Model.dc()`, so SDCStudio's field defaults ("Universal" coverage, "None"
relation) come back as null rather than as what the modeler said.

The protocol handling lives in `sdcreader.mcp`, shared with the projection
servers. Reuse, do not reimplement: every tool calls the same functions the
library exposes.
"""

from __future__ import annotations

from typing import Any

from sdcreader import __version__
from sdcreader.mcp import (MCP_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS, PackageCache, Server, ToolError,
                           int_arg, source_properties)
from sdcreader.model import EXACT, IDENTIFIER, PUBLISHER, SEE_ALSO, SOURCE
from sdcreader.package import DEFAULT_HOST, fetch_package  # noqa: F401  (fetch_package is patched by tests)

__all__ = ["TOOLS", "TOOL_HANDLERS", "MCP_PROTOCOL_VERSION", "SUPPORTED_PROTOCOL_VERSIONS", "main", "run_stdio"]

SERVER_NAME = "sdcreader"
SERVER_VERSION = __version__
ISSUES = "https://github.com/SemanticDataCharter/sdcreader/issues"

#: Set once by `main()`, never from tool arguments.
_HOST: str = DEFAULT_HOST
#: The process-wide package cache's storage; a published package is immutable.
_CACHE: dict = {}

DEFAULT_PAGE = 50
MAX_PAGE = 200
DEFAULT_FIND = 20
MAX_FIND = 100

ReaderToolError = ToolError

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
        "inputSchema": {"type": "object", "properties": source_properties(), "additionalProperties": False},
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
                **source_properties(),
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
                **source_properties(),
                "component": {"type": "string", "description": "The component's identifier (ct_id), as list_leaves reports it."},
            },
            "required": ["component"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_record",
        "description": (
            "Read a Governed Data Record (an XML file on disk) against its model: the record's attributes and each "
            "value in document order with its component, path of clusters, elements, context and any Exceptional "
            "Value (ISO 21090 code, name, and whether it was written at the source or inserted by recovery beside a "
            "rejected value). The model is the one the record names, fetched by its identifier unless ct_id or "
            "directory is given. Paged. Does not validate the record."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "record": {"type": "string", "description": "Path to the record's XML file on disk."},
                **source_properties(),
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE, "default": DEFAULT_PAGE},
            },
            "required": ["record"],
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
            "properties": {"directory": source_properties()["directory"]},
            "required": ["directory"],
            "additionalProperties": False,
        },
    },
]


def _cache() -> PackageCache:
    # Built per call so a test that swaps `_HOST` or patches `fetch_package` on this module is honored; the storage
    # dict is shared, so a package is still read once per process.
    import sdcreader.mcp_server as me

    return PackageCache(host=_HOST, storage=_CACHE, fetcher=lambda ct_id, host: me.fetch_package(ct_id, host=host))


def _links(component) -> dict[str, list[str]]:
    names = {IDENTIFIER: "identifier", SOURCE: "source", PUBLISHER: "publisher", EXACT: "exactMatch", SEE_ALSO: "seeAlso"}
    return {short: list(component.links[pred]) for pred, short in names.items() if component.links.get(pred)}


def _handle_find_models(args: dict[str, Any]) -> Any:
    import requests

    search = args.get("search", "")
    project = args.get("project", "")
    if not isinstance(search, str) or not isinstance(project, str):
        raise ToolError("`search` and `project` must be strings.")
    page = int_arg(args, "page", 1, 1, 10_000)
    page_size = int_arg(args, "page_size", DEFAULT_FIND, 1, MAX_FIND)
    params = {"format": "json", "page": page, "page_size": page_size}
    if search:
        params["search"] = search
    if project:
        params["project"] = project
    try:
        r = requests.get(f"{_HOST}/api/v1/catalog/dms/", params=params, timeout=60)
    except requests.RequestException as exc:
        raise ToolError(f"The catalog could not be reached: {exc}") from exc
    if r.status_code != 200:
        raise ToolError(f"The catalog answered HTTP {r.status_code}.")
    data = r.json()
    return {
        "host": _HOST,
        "count": data.get("count"),
        "page": page,
        "page_size": page_size,
        "models": [
            {"ct_id": m.get("ct_id"), "title": m.get("title"), "project": m.get("project_name"),
             "description": (m.get("description") or "")[:300], "updated": m.get("updated")}
            for m in data.get("results", [])
        ],
        "hint": "Pass a ct_id to describe_model. Models are listed only from public projects.",
    }


def _handle_describe_model(args: dict[str, Any]) -> Any:
    pkg, model = _cache().one(args)
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
    pkg, model = _cache().one(args)
    offset = int_arg(args, "offset", 0, 0, 10_000_000)
    limit = int_arg(args, "limit", DEFAULT_PAGE, 1, MAX_PAGE)
    page = model.leaves[offset : offset + limit]
    leaves = [
        {
            "position": leaf.position, "slug": leaf.slug, "ct_id": leaf.component.ct_id, "label": leaf.component.label,
            "sdc_type": leaf.component.sdc_type, "data_type": leaf.component.data_type, "path": [p.label for p in leaf.path],
            "description": leaf.component.description, "constraints": leaf.component.constraints,
            "codes": len(model.codes.get(leaf.component.ct_id, [])), "links": _links(leaf.component),
        }
        for leaf in page
    ]
    return {
        "ct_id": model.ct_id, "title": model.title, "total": len(model.leaves), "offset": offset, "limit": limit,
        "returned": len(leaves), "next_offset": offset + limit if offset + limit < len(model.leaves) else None, "leaves": leaves,
    }


def _handle_list_codes(args: dict[str, Any]) -> Any:
    pkg, model = _cache().one(args)
    comp_id = args.get("component")
    if not isinstance(comp_id, str) or not comp_id:
        raise ToolError("`component` must be a component identifier (ct_id).")
    comp = model.components.get(comp_id)
    if comp is None:
        raise ToolError(f"No component {comp_id!r} in model {model.ct_id}. list_leaves reports the identifiers.")
    codes = model.codes.get(comp_id, [])
    return {
        "ct_id": model.ct_id,
        "component": {"ct_id": comp.ct_id, "label": comp.label, "sdc_type": comp.sdc_type, "links": _links(comp)},
        "count": len(codes),
        "codes": [{"value": k.value, "iri": k.iri, "definition": k.definition, "defined_by": k.defined_by} for k in codes],
        "hint": None if codes else "This component has no enumerated values in the published schema.",
    }


def _handle_read_record(args: dict[str, Any]) -> Any:
    import re
    from pathlib import Path

    from sdcreader.record import RecordError, read_record

    path = args.get("record")
    if not isinstance(path, str) or not path:
        raise ToolError("`record` must be a path to the record's XML file.")
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ToolError(f"Could not read the record: {exc}") from exc
    source = {k: args[k] for k in ("ct_id", "directory") if args.get(k)}
    if not source:
        m = re.search(rb"<[A-Za-z0-9_]+:dm-([a-z0-9]{24})[\s>]", data[:4000])
        if not m:
            raise ToolError("The record does not name a model (no sdc4:dm-<ct_id> root); give ct_id or directory.")
        source = {"ct_id": m.group(1).decode()}
    pkg, model = _cache().one(source)
    try:
        record = read_record(data, model)
    except RecordError as exc:
        raise ToolError(str(exc)) from exc
    offset = int_arg(args, "offset", 0, 0, 10_000_000)
    limit = int_arg(args, "limit", DEFAULT_PAGE, 1, MAX_PAGE)
    page = record.values[offset : offset + limit]
    values = [
        {
            "position": v.position, "ct_id": v.component.ct_id, "label": v.component.label, "sdc_type": v.component.sdc_type,
            "path": [p.label for p in v.path], "occurrence": v.occurrence, "elements": v.elements, "context": v.context,
            "exceptional": ({"code": v.exceptional.code, "name": v.exceptional.name, "origin": v.exceptional.origin}
                            if v.exceptional else None),
        }
        for v in page
    ]
    return {
        "ct_id": model.ct_id, "title": model.title, "schema_sha256": pkg.sha256, "attributes": record.attributes,
        "total": len(record.values), "exceptional": len(record.exceptional), "offset": offset, "limit": limit,
        "returned": len(values), "next_offset": offset + limit if offset + limit < len(record.values) else None, "values": values,
    }


def _handle_check_package(args: dict[str, Any]) -> Any:
    from sdcreader.package import PackageError, load_package

    directory = args.get("directory")
    if not isinstance(directory, str) or not directory:
        raise ToolError("`directory` must be a string path.")
    try:
        pkg = load_package(directory, host=_HOST)
    except PackageError as exc:
        return {"ok": False, "directory": directory, "error": str(exc)}
    except OSError as exc:
        raise ToolError(f"Could not read the package: {exc}") from exc
    return {
        "ok": True, "directory": directory, "ct_id": pkg.ct_id, "schema_sha256": pkg.sha256,
        "schema_url_pinned": pkg.schema_url_pinned, "published_current_sha256": pkg.versions.get("current_sha256"),
        "versions_present": bool(pkg.versions), "catalog_present": bool(pkg.catalog),
    }


TOOL_HANDLERS = {
    "find_models": _handle_find_models,
    "describe_model": _handle_describe_model,
    "list_leaves": _handle_list_leaves,
    "list_codes": _handle_list_codes,
    "check_package": _handle_check_package,
    "read_record": _handle_read_record,
}


def _server() -> Server:
    return Server(
        name=SERVER_NAME, version=SERVER_VERSION, tools=TOOLS, handlers=TOOL_HANDLERS, issues_url=ISSUES,
        instructions=(
            "Read published Semantic Data Charter models. `find_models` searches "
            f"the public catalog at {_HOST}; `describe_model`, `list_leaves` and "
            "`list_codes` read one model by its ct_id from that host or from a "
            "package directory on disk; `check_package` verifies a directory; "
            "`read_record` reads a Governed Data Record on disk against its model. "
            "All tools are read-only and need no account. No tool takes a URL."
        ),
    )


def _handle_request(request: Any) -> dict | None:
    return _server().handle(request)


def run_stdio() -> None:
    _server().run_stdio()


def main(argv: list[str] | None = None) -> None:
    """Entry point for `sdcreader` and `sdcreader-mcp`."""
    import argparse

    global _HOST

    parser = argparse.ArgumentParser(prog="sdcreader-mcp", description="MCP stdio server for reading published Semantic Data Charter models.")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"The SDCStudio host whose public catalog is read, fixed here so a caller cannot redirect the server. Default {DEFAULT_HOST}.")
    args = parser.parse_args(argv)
    _HOST = args.host.rstrip("/")
    run_stdio()


if __name__ == "__main__":
    main()
