# sdcreader PRD: one reader for SDC model packages, shared by every projection

**Status:** v0.1, 9 October 2026, DRAFT for Tim. The shared tool the projections track (ContentStrategy lane 5.6)
said would appear when the third repository repeated the second; it is now the fourth. Tim, 9 October: "only the
loader and model reader should be abstracted into one tool that can be reused across projections." Repository
`SemanticDataCharter/sdcreader`, public, Apache-2.0, to be published on PyPI as `sdcreceipt` is.

## 1. Facts

**What exists.** Two modules, `package.py` (106 lines) and `model.py` (233 lines), byte-identical in all four
projection repositories (`sdc_cdif/src/sdccdif`, `sdc_dcat3_us/src/sdcdcatus`, `sdc_dcat3_ap/src/sdcdcatap`,
`sdc_healthdcat_ap/src/sdchealthdcatap`), copied forward with each new writer and patched in all four whenever one
learned something (the catalog's storage pointer, the schema header's Dublin Core). Nothing in them knows which
projection is calling.

**What they do.**
- `package.py`: a published model's **package** as the evidence a projection describes. `ModelPackage` holds the
  model's JSON-LD (`dm-<ct>.jsonld`: the model and its components with cardinality, constraints and semantic
  links), the schema bytes (`dm-<ct>.xsd`), the public catalog record (`catalog.json`) and the published schema
  versions (`versions.json`); it computes the SHA-256, the `/dmlib/` schema URL and its pinned form (`?sha256=`),
  and the public catalog URL, and `check()` refuses a package whose identifier, components or schema are wrong or
  whose schema bytes are not the published current version. `load_package(dir)` reads one from disk and refuses a
  model without one ("the writer needs the model's package, not just its identifier"). `fetch_package(ct_id)`
  takes one from SDCStudio's public catalog with no account: the catalog record, the JSON-LD (following the
  storage pointer the artifact endpoint answers with), the schema from `/dmlib/`, the versions; optionally saved.
- `model.py`: the package read into the shape a projection needs. `Component` (type, label, description, XSD
  datatype, constraints, semantic links by predicate, members), `Leaf` (a leaf component with its path of clusters
  and its position, and a `slug` of the path), `Code` (an enumerated value with the IRI, definition and code the
  schema annotates it with), `Model` (the root cluster found as the largest uncontained one, the leaves in document
  order, the enumeration codes read from the schema, the JSON-LD metadata, and the schema header's Dublin Core).
  `Model.dc(name)` returns what the modeler wrote, the schema header first and the JSON-LD second, with SDCStudio's
  field defaults ("Universal" coverage, "None" relation, "SDC Data Model (DM)" type, blanks) as unset;
  `contributors`, `subjects` (the semicolon list), `rights_url` and `rights_statement` derive from it.
  `read_header()` parses the header; `enumeration_iri()` names a component's value set as the parent of the
  per-value class IRIs the schema declares. The leaf types, the numeric and quantified types, and the predicate
  IRIs (`dcterms:identifier`, `source`, `publisher`, `skos:exactMatch`, `closeMatch`, `rdfs:seeAlso`,
  `sdc4-meta:hasUnit`) are module constants.

**What depends on them.** Each projection's emitter: `sdccdif.cdif` (CDIF), `sdcdcatus.dcatus` (DCAT-US 3.0),
`sdcdcatap.dcatap` (DCAT-AP 3.0.1), `sdchealthdcatap.healthdcatap` (HealthDCAT-AP, which also depends on the
DCAT-AP graph builder, the standard's own dependence and not a general one). Their tests use the NHANES Participant
package (`xy8upneajsb8vdcmnve01g6g`, FAIR Data Demo) committed under `samples/`.

**What the package format is.** It is SDCStudio's generated package, public for every model in a public project:
`/api/v1/catalog/dm/<ct>/` (the record), `/api/v1/catalog/dm/<ct>/<artifact>/` (a storage pointer for jsonld, xsd
and the rest), `/dmlib/dm-<ct>.xsd` (the schema bytes), `/dmlib/dm-<ct>.versions.json` (every published version by
SHA-256). Two gaps in it are on SDCStudio's issue tracker: the JSON-LD metadata drops fields the XSD header carries
(#748) and the header omits `dc:source` (#749). The reader works around the first by reading the header.

**Precedent.** `sdcreceipt` (Apache-2.0, `src/` layout, PyPI 4.2.4) is the model for a standalone Semantic Data
Charter package: one implementation, a CLI over it, tests that need no account.

## 2. Rules

1. **One deliverable: the package `sdcreader`**, the two modules as they are, with their own tests, published, and
   the four projections depending on it instead of carrying a copy.
2. **No projection knowledge.** `sdcreader` reads; it never writes CDIF, DCAT or anything else. A function that is
   useful to one projection only stays in that projection. The DCAT-AP graph builder is not here.
3. **The API is the four copies' API,** unchanged in the first release, so the four switch-overs are mechanical:
   `from sdcreader import ModelPackage, load_package, fetch_package, read_model, Model, Component, Leaf, Code,
   PackageError` and the constants. **Versioning as everything in the Semantic Data Charter is versioned: the
   leading 4 is the SDC4 reference model** (Tim, 9 October; `sdcreceipt` 4.2.4, `sdcgovernance` 4.2.x, SDCStudio
   4.14.x). The first release is **4.0.0**; an addition to what `Model` exposes is a minor version, a fix a patch;
   the major changes only when the reference model does (SDC5 reads as 5.x). The four projection packages, released
   at 0.1.0 by oversight, move to 4.0.0 in their switch-over pull requests.
4. **The package format is documented here,** once, as the contract the reader relies on (section 1, "what the
   package format is"), with the SDCStudio issues that affect it.
5. **Tests need no account and no network:** the NHANES Participant package is the committed fixture; `fetch_package`
   is tested against it by a fake transport, plus one network-marked test against production that CI skips.
6. **Attribution and licence.** Apache-2.0, `NOTICE` naming the FAIR Data Demo package as the fixture; en-US;
   "Governed Data Record"; the Semantic Data Charter named as the framework.

## 3. Scope

### 3.1 First: the package
`src/sdcreader/package.py` and `model.py` moved from the four copies (identical, so from any one), `__init__.py`
exporting the API, `pyproject.toml` (`lxml`; `requests` as the `fetch` extra; `pytest` as `dev`), `samples/
nhanes-participant/` as the fixture, `tests/` (loading, refusals, the header's Dublin Core with defaults as unset,
the leaves and codes, the storage pointer, the schema versions), CI, README (what a package is, what the reader
gives, how the projections use it), `NOTICE`, dev to main by pull request with merge commits. Tag `v4.0.0`.

### 3.2 Then: the four switch-overs
One pull request per projection: delete the copy, add `sdcreader>=4.0,<5` to the dependencies, change the import,
set the projection's own version to 4.0.0 (rule 3), run the tests, update the README's layout section. Until the PyPI release exists, the dependency is the git tag
(`sdcreader @ git+https://github.com/SemanticDataCharter/sdcreader@v4.0.0`); after it, the version.

### 3.3 Later
- A small CLI, `sdcreader fetch --ct-id ID DIR` and `sdcreader show DIR` (the leaves, the codes, the header), for
  anyone looking at a package before projecting it.
- Whatever SDCStudio's #748 and #749 change in the package, reflected here in one place.
- A projection that reads a collection of records (a CordovaOS domain) rather than a model would add a record
  reader beside the model reader, still with no projection knowledge.

## 4. Decisions (proposed; open for Tim)
1. **Name and layout:** package `sdcreader`, modules `sdcreader.package` and `sdcreader.model`, the `sdcreceipt`
   layout, version **4.0.0** (rule 3).
2. **PyPI publication by Tim**, as `sdcreceipt` is published, with a release workflow that builds on a `v*` tag and
   publishes through PyPI trusted publishing once the project is registered there; until then the git tag is the
   dependency.
3. **The DCAT-AP graph builder stays in `sdc_dcat3_ap`**; HealthDCAT-AP keeps its copy of it for now. Publishing
   `sdcdcatap` as a dependency is a separate decision, not forced by this one.
4. **The fixture is the NHANES Participant package** (1.3 MB), the same record as every projection, so a reader
   change is proven on the record the projections are proven on.
5. **No CLI in 4.0.0** (section 3.3), so the first release is the four copies made one and nothing else.

## 5. Pipeline
`src/sdcreader/` from the copies, then `tests/` against `samples/nhanes-participant/`, then CI, then the tag, then
the four switch-over pull requests in the order the repositories were built.
