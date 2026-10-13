# Changelog

Versions carry the leading 4 of the SDC4 reference model: an addition to what the reader exposes is a minor version, a
fix a patch, and the major changes only when the reference model does.

## 4.2.0 (2026-10-13)

`sdcreader.mcp`: the MCP scaffold the SDC servers share, lifted out of `sdcreader.mcp_server` so the four projection
servers (`sdccdif`, `sdcdcatus`, `sdcdcatap`, `sdchealthdcatap`) do not carry copies. `Server` (JSON-RPC 2.0 over
stdio, protocol negotiation, `isError` tool results, the request guards), `ToolError`, `PackageCache` (the
`ct_id`-or-`directory` source argument, singular and plural, read once per process), `source_properties`, `int_arg`,
`str_arg`. The reader's own server is unchanged in behaviour and now built on it.

## 4.1.0 (2026-10-13)

An MCP server, `sdcreader.mcp_server`, registered as `io.github.SemanticDataCharter/sdcreader`: five read-only tools
(`find_models`, `describe_model`, `list_leaves`, `list_codes`, `check_package`) over the same functions the library
exposes; stdio, hand-rolled JSON-RPC, protocol revisions 2025-06-18 and 2025-11-25 negotiated, tool failures returned
as `isError` results. The catalog host is fixed at start (`--host`); no tool takes a URL. Console scripts `sdcreader`
and `sdcreader-mcp`. `requests` moves into the base dependencies so `uvx sdcreader` can fetch; the `fetch` extra is
kept empty for compatibility. `server.json` and a `publish-mcp` release job publish the registry entry on each tag.

## 4.0.0 (2026-10-09)

The loader and model reader that four projection writers carried as identical copies (`sdc_cdif`, `sdc_dcat3_us`,
`sdc_dcat3_ap`, `sdc_healthdcat_ap`), made one package with the same API:
`ModelPackage`, `load_package`, `fetch_package`, `read_model`, `read_header`, `enumeration_iri`, `Model`, `Component`,
`Leaf`, `Code`, `PackageError`, and the type and predicate constants.
