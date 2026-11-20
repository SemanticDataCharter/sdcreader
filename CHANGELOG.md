# Changelog

Versions carry the leading 4 of the SDC4 reference model: an addition to what the reader exposes is a minor version, a
fix a patch, and the major changes only when the reference model does.

## 4.5.0 (2026-11-20)

The reference-model parts beyond the data cluster. 4.4 read only the DM's data cluster, so a record's subject, its
providers, its Participations, its workflow and its attestation reached no caller, and no mapper could write a FHIR
Composition's author or subject from an SDCHealth record. Everything here is opt-in: without the new flag a record reads
exactly as in 4.4, value for value.

- **`read_record(source, model, reference_model=True)`** also reads, where the SDC4 reference model puts them, the DM's
  `subject` and `provider` (Parties), its Participations (`performer`, `function`, `mode`, `start`, `end`), `protocol`,
  `workflow`, `acs`, Audits (`system-id`, `system-user`, `location`, `timestamp`) and `attestation` (`view`, `proof`,
  `reason`, `committer`, `committed`, `pending`), and every Party's `party-name`, `party-ref` and `party-details`.
  A value inside one of these is read against the component the generated schema types its element by (a
  Participation's performer, a Party's details cluster, a Participation's function), so a caller names a Party's
  details and their components by the same identifiers as data-cluster components. Where the schema leaves the
  reference model's own type (SDCStudio declares a DM's subject, provider and attestation as `sdc4:PartyType` and
  `sdc4:AttestationType`), the component is the one the record's label names; where nothing names one, the reader
  makes a component for the element (`rm_component`), whose ct_id is the element's name. An element of a simple type is
  read as the value type that holds the same thing: a Participation's `start` as an XdTemporal datetime, an
  Attestation's `pending` as an XdBoolean, a Party's `party-name` as an XdString. Exceptional Values are read as in the
  data cluster.
- **`RecordValue.roles`** (parallel to `path`) and **`RecordValue.role`** name the reference-model element each step of a
  value's path, and the value itself, stands in (`("subject", "party-details", "")`, `"start"`), so a caller tells the
  subject's details from the provider's, or the Attester's from the Legal Authenticator's, where one details cluster
  serves several Parties. `Record.reference_model` and `Record.parts`.
- **`walk_values(root, model, reference_model)`**: the reader's own walk over a record's value elements, in the order it
  numbers them, for a caller holding the tree (sdc-mapper's gate places the Exceptional Values it inserts by it).
- **`Model.slots`**: the reference-model elements the schema declares for the DM and for each Party, Participation,
  Attestation and Audit, each naming the component its type is or the reference model's own type;
  `slot_component()`, `placed`, `unplaced_parties` (the Parties a record's subject or provider can be), and
  `part_leaves()`, the parts' leaves with their `roles`. `RM_SLOTS`, `RM_PARTS` and `RM_ELEMENTS` name the elements.
- **Fix: `Model.root` is the data cluster the DM's complexType names.** 4.4 took the largest cluster no other contains,
  which in an SDCHealth model is a Patient's details cluster. Of the 36 packages on disk across the projection and
  mapper repositories, only the SDCHealth Laboratory Report's root changes.
- **MCP:** `describe_model` reports the reference-model parts (`reference_model`); `list_leaves` takes `parts` to list
  their leaves with `roles`; `read_record` takes `reference_model` and then reports `path_ct_ids`, `roles`, `role` and
  `parts`. The tool set is unchanged.
- Fixture: the SDCHealth Laboratory Report package (production, public) and two synthetic records of it.

## 4.4.1 (2026-10-25)

Rebuilt with pip 26.2.2 pinned by hash in CI and the release job (the eMudhra/emSign CA compromise: pip before 26.2.2 trusts the compromised root through its vendored certifi). No change to the package.

## 4.4.0 (2026-10-25)

Cluster instances. Every `RecordValue` carries `instances`, parallel to its `path`: which occurrence each cluster is
among the same cluster's repeats under the same parent instance; `instance_key` pairs them with the clusters'
identifiers. A record-level mapper writes one target element per cluster instance (one UBL `InvoiceLine` per line)
and could not tell two repeats of a cluster under the same parent apart before. **Changed:** `occurrence` now counts a
value's repeats within its cluster instance, not across every instance under the same path, so the second line's first
value is occurrence 0 of instance 1 rather than occurrence 1. The MCP tool `read_record` reports `instances`.

## 4.3.1 (2026-10-24)

Fix: a recovery Exceptional Value beside an ordinal, a link, a file or an interval was read as one written at the
source, and its rejected value was not offered as `rejected`. The reader recognized a value element only by a name
ending in `-value` or starting with `xdtemporal-`; it now uses `VALUE_ELEMENTS`, every value element the SDC4
reference model defines (`ordinal`, `symbol`, `link`, `uri`, `media-content`, `lower`, `upper` among them). Found while
building `sdc-mapper`'s value typing against sdc4.xsd.

`ExceptionalValue.origin` is documented as what it is: inferred from the record's shape. A published model may require
the value element, as SDCStudio's generated schemas do, and then an Exceptional Value written at the source sits beside
a value as well; a caller that inserted Exceptional Values itself (sdc-mapper's gate) knows the origin for certain.

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
