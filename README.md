# sdcreader

Read a published Semantic Data Charter model's package for projection into other standards.

A projection describes a model's governed data records in another standard's terms: CDIF, DCAT-US 3.0, DCAT-AP
3.0.1, HealthDCAT-AP, and whatever comes next. What every projection describes is the same evidence, the model's
package, and reads it into the same shape. `sdcreader` is that evidence and that shape, once, with nothing about
any projection in it. The four projection writers (`sdc_cdif`, `sdc_dcat3_us`, `sdc_dcat3_ap`, `sdc_healthdcat_ap`)
carried it as identical copies until this package.

```
pip install sdcreader            # or, until the PyPI release: pip install "sdcreader @ git+https://github.com/SemanticDataCharter/sdcreader@v4.0.0"
pip install "sdcreader[fetch]"   # with HTTP, to fetch a package from the public catalog
```

```python
from sdcreader import fetch_package, load_package, read_model

pkg = load_package("samples/nhanes-participant")          # a package on disk
pkg = fetch_package("xy8upneajsb8vdcmnve01g6g", save_to="pkg/")   # or from SDCStudio's public catalog, no account
model = read_model(pkg)

pkg.schema_url_pinned        # https://sdcstudio.axius-sdc.com/dmlib/dm-xy8u...xsd?sha256=0df4...   the exact bytes the records are validated against
model.title, model.leaves    # 'NHANES Participant', 153 leaves in document order, each with its path of clusters
model.codes[ct_id]           # the enumerated values of a component with the IRI, definition and code the schema annotates them with
model.dc("publisher")        # what the modeler wrote, None where SDCStudio's default sits
```

## What a package is

SDCStudio generates a package for every published model and serves it publicly for models in public projects:

| | |
|---|---|
| `GET /api/v1/catalog/dm/<ct>/` | the catalog record: title, description, project, the artifact list (`catalog.json`) |
| `GET /api/v1/catalog/dm/<ct>/<artifact>/` | a storage pointer, `{"download_url": ..., "filename": ..., "storage": "gcs"}`, for `jsonld`, `xsd` and the rest; the reader follows it |
| `dm-<ct>.jsonld` | the model and its components: type, label, description, cardinality, constraints (enumerations, units, ranges, patterns), semantic links (`dcterms:identifier` the library slot, `dcterms:source`, `dcterms:publisher`, `skos:exactMatch`, `rdfs:seeAlso`, `prov:wasRevisionOf`), `contains` |
| `GET /dmlib/dm-<ct>.xsd` | the schema bytes: the Dublin Core header for the model, and for each enumerated value its definition and the code it is defined by (`dm-<ct>.xsd`) |
| `GET /dmlib/dm-<ct>.versions.json` | every published version of the schema by SHA-256, with the current one (`versions.json`) |

A package directory holds those four files. The reader refuses a directory without the JSON-LD and the schema, a
JSON-LD whose identifier is not the directory's model, and a schema whose bytes are not the published current
version: a projection cites the schema by URL and SHA-256, so the bytes have to be the ones that URL serves.

Two gaps in the package are on SDCStudio's issue tracker: the JSON-LD metadata drops fields the schema header
carries (#748), and the header omits `dc:source` (#749). The reader takes the model's Dublin Core from the header,
which is complete.

## What the reader gives

- **`ModelPackage`**: the four files, the SHA-256, the schema URL and its pinned form (`?sha256=`), the public
  catalog URL, and `check()`.
- **`Model`**: `title`, `description`, `root` (the governed record's cluster), `components` by identifier, `leaves`
  in document order (each a `Leaf` with its `component`, its `path` of clusters and a `slug` of that path, unique in
  the record), `codes` (the enumerated values per component as `Code`: value, IRI, definition, the code it is
  defined by), `metadata` (the JSON-LD's) and `header` (the schema's Dublin Core).
- **`Model.dc(name)`**: what the modeler wrote, the header first and the JSON-LD second, with SDCStudio's field
  defaults as unset: "Universal" for coverage, "None" for relation, "SDC Data Model (DM)" for type, blanks. A
  projection never publishes a default as a fact. `contributors`, `subjects` (the semicolon list), `rights_url` and
  `rights_statement` derive from it.
- **`Component`**: `sdc_type`, `label`, `description`, `data_type`, `constraints`, `links` by predicate (`link(p)` for
  the first), `contains`, `iri`.
- Constants: the leaf, numeric and quantified types; the predicate IRIs `IDENTIFIER`, `SOURCE`, `PUBLISHER`, `EXACT`,
  `CLOSE`, `SEE_ALSO`, `HAS_UNIT`; `DC_DEFAULTS`.

## Tests

```
pip install -e ".[dev]"
python -m pytest tests -q                    # includes one fetch against production
python -m pytest tests -q -m "not network"   # offline, as CI runs it
```

The fixture is the NHANES Participant package of the FAIR Data Demo, the record every projection is proven on.

## Versioning

The leading 4 is the SDC4 reference model, as with every Semantic Data Charter package. An addition to what the
reader exposes is a minor version, a fix a patch; the major changes only when the reference model does.

## Licence

Apache-2.0 (see `LICENSE`, `NOTICE`).
