"""The reader on the NHANES Participant package: it loads and refuses as documented, proves the schema bytes are the
published current version, reads the record tree and its leaves in document order, the enumerated values with their
codes, the model's Dublin Core with SDCStudio's defaults as unset, and fetches a package from the public catalog
following the storage pointer (through a fake transport offline; against production behind the network marker)."""
import hashlib
import json
from pathlib import Path

import pytest

import sdcreader
from sdcreader import Code, Leaf, Model, PackageError, enumeration_iri, fetch_package, load_package, read_header, read_model

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "samples" / "nhanes-participant"
CT = "xy8upneajsb8vdcmnve01g6g"


@pytest.fixture(scope="module")
def pkg():
    return load_package(PACKAGE)


@pytest.fixture(scope="module")
def model(pkg):
    return read_model(pkg)


def test_the_version_carries_the_reference_model():
    assert sdcreader.__version__.startswith("4.")


def test_a_package_loads_and_proves_its_schema_is_the_published_current_version(pkg):
    assert pkg.ct_id == CT
    sha = hashlib.sha256((PACKAGE / f"dm-{CT}.xsd").read_bytes()).hexdigest()
    assert pkg.sha256 == sha == pkg.versions["current_sha256"]
    assert pkg.schema_url == f"https://sdcstudio.axius-sdc.com/dmlib/dm-{CT}.xsd"
    assert pkg.schema_url_pinned == f"{pkg.schema_url}?sha256={sha}"
    assert pkg.catalog_url == f"https://sdcstudio.axius-sdc.com/api/v1/catalog/dm/{CT}/"
    assert pkg.catalog["project_name"] == "FAIR Data Demo"


def test_the_reader_refuses_what_is_not_a_package(tmp_path):
    (tmp_path / f"dm-{CT}.xsd").write_bytes(b"<xsd:schema/>")
    with pytest.raises(PackageError, match="missing"):
        load_package(tmp_path)
    (tmp_path / f"dm-{CT}.jsonld").write_text(json.dumps({"identifier": "other", "components": [{}]}))
    with pytest.raises(PackageError, match="identifier"):
        load_package(tmp_path)
    (tmp_path / f"dm-{CT}.jsonld").write_text(json.dumps({"identifier": CT, "components": [{}]}))
    (tmp_path / "versions.json").write_text(json.dumps({"current_sha256": "0" * 64}))
    with pytest.raises(PackageError, match="not the published current version"):
        load_package(tmp_path)


def test_the_record_tree_its_leaves_and_their_codes(model: Model):
    assert model.title == "NHANES Participant" and model.root.label == "NHANES Participant Governed Record"
    assert len(model.leaves) == 153
    first, last = model.leaves[0], model.leaves[-1]
    assert isinstance(first, Leaf) and first.position == 0 and last.position == 152
    assert first.slug.startswith("audit-event/") and all(l.component.sdc_type in sdcreader.LEAF_TYPES for l in model.leaves)
    slugs = [l.slug for l in model.leaves]
    assert len(set(slugs)) == len(slugs)                                      # the path names each leaf once
    assert len({l.component.ct_id for l in model.leaves}) < len(slugs)        # a component composed three times (the blood pressure readings) is three leaves
    enumerated = {k: v for k, v in model.codes.items() if k in model.components}
    assert len(enumerated) >= 60
    marital = next(l.component for l in model.leaves if l.component.label == "Marital Status (DMDMARTL)")
    codes = model.codes[marital.ct_id]
    assert [c.value for c in codes][:2] == ["Married", "Widowed"]
    assert all(isinstance(c, Code) and c.iri.startswith(marital.iri) for c in codes)
    assert codes[0].defined_by == "http://purl.obolibrary.org/obo/NCIT_C51773"
    assert enumeration_iri(marital, codes) == f"{marital.iri}/xdtoken-value"
    sbp = next(l.component for l in model.leaves if l.component.label == "Systolic Blood Pressure")
    assert sbp.sdc_type == "XdQuantity" and sbp.data_type == "xsd:decimal" and sbp.link(sdcreader.IDENTIFIER).startswith("https://axius-sdc.com/library/")


def test_the_models_dublin_core_comes_from_the_schema_header_with_defaults_as_unset(model: Model, pkg):
    header = read_header(pkg.xsd_bytes)
    assert header["coverage"] == "Universal" and header["relation"] == "None" and header["publisher"] == ""
    assert model.dc("coverage") is None and model.dc("relation") is None and model.dc("publisher") is None and model.dc("type") is None
    assert model.dc("creator") == "Timothy Cook" and model.dc("date", ).startswith("2026-09-26")
    assert model.subjects == [] and model.contributors == []
    assert model.rights_url == "http://creativecommons.org/licenses/by/3.0/" and model.rights_statement == ""
    authored = Model(**{**model.__dict__, "header": dict(header, subject="a; b;; c", contributor=["X"],
                                                          rights="Public domain in the United States https://creativecommons.org/publicdomain/zero/1.0/ except where noted")})
    assert authored.subjects == ["a", "b", "c"] and authored.contributors == ["X"]
    assert authored.rights_url == "https://creativecommons.org/publicdomain/zero/1.0/" and authored.rights_statement.startswith("Public domain")


def test_fetch_follows_the_catalogs_storage_pointer(monkeypatch, tmp_path):
    """The artifact endpoint answers with {download_url, filename, storage} for a storage-backed file, not the file."""
    import requests
    files = {
        f"https://sdcstudio.axius-sdc.com/api/v1/catalog/dm/{CT}/": (PACKAGE / "catalog.json").read_bytes(),
        f"https://sdcstudio.axius-sdc.com/api/v1/catalog/dm/{CT}/jsonld/": json.dumps({"download_url": "https://storage.example/dm.jsonld", "filename": "x", "storage": "gcs"}).encode(),
        "https://storage.example/dm.jsonld": (PACKAGE / f"dm-{CT}.jsonld").read_bytes(),
        f"https://sdcstudio.axius-sdc.com/dmlib/dm-{CT}.xsd": (PACKAGE / f"dm-{CT}.xsd").read_bytes(),
        f"https://sdcstudio.axius-sdc.com/dmlib/dm-{CT}.versions.json": (PACKAGE / "versions.json").read_bytes(),
    }

    class R:
        def __init__(self, content):
            self.status_code, self.content = 200, content

        def json(self):
            return json.loads(self.content)

    monkeypatch.setattr(requests, "get", lambda url, **kw: R(files[url]))
    pkg = fetch_package(CT, save_to=tmp_path)
    assert pkg.sha256 == load_package(PACKAGE).sha256 and pkg.jsonld["identifier"] == CT
    assert sorted(p.name for p in tmp_path.iterdir()) == ["catalog.json", f"dm-{CT}.jsonld", f"dm-{CT}.xsd", "versions.json"]
    assert load_package(tmp_path).sha256 == pkg.sha256


@pytest.mark.network
def test_fetch_from_production_matches_the_fixture():
    pkg = fetch_package(CT)
    assert pkg.sha256 == load_package(PACKAGE).sha256
