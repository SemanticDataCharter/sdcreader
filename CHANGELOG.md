# Changelog

Versions carry the leading 4 of the SDC4 reference model: an addition to what the reader exposes is a minor version, a
fix a patch, and the major changes only when the reference model does.

## 4.3.0 (2026-10-24)

`sdcreader.record`: the reader reads a Governed Data Record itself, for record-level mappers (`sdc-mapper`).
`read_record(source, model)` parses the XML instance, refuses a record of another model, passes through the adapter
elements a cluster's members sit in, and returns a `Record` (the record's attributes and its values in document
order) of `RecordValue`s (component, path of clusters, occurrence, position, the value elements as held, nested where
the record nests them, and the per-value context). Exceptional Values (the sixteen ISO 21090 null flavors of the SDC4
reference model) are read with their origin: `source` when written in place of the value, `recovery` when
sdcvalidator inserted one beside a value that failed its constraint, which stays available as `rejected`. Read across
HalvorsenDemo's 593 generated records (129,628 values, eight models) with every value populated. MCP tool
`read_record`; a second fixture, a HalvorsenDemo Credit Note record and its model's package.

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
