"""A published model's package: the files the writer reads, from a directory or from SDCStudio's public catalog.

A package directory holds `dm-<ct>.jsonld` (the model and its components with their semantic links), `dm-<ct>.xsd`
(the schema, read for the enumeration definitions and hashed for the citation), and optionally `catalog.json` (the
public catalog record) and `versions.json` (the published schema versions). The writer refuses a model without a
package: the JSON-LD and the schema are the evidence it describes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOST = "https://sdcstudio.axius-sdc.com"


class PackageError(Exception):
    pass


@dataclass
class ModelPackage:
    ct_id: str
    jsonld: dict
    xsd_bytes: bytes
    catalog: dict = field(default_factory=dict)
    versions: dict = field(default_factory=dict)
    host: str = DEFAULT_HOST

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.xsd_bytes).hexdigest()

    @property
    def schema_url(self) -> str:
        return f"{self.host}/dmlib/dm-{self.ct_id}.xsd"

    @property
    def schema_url_pinned(self) -> str:
        return f"{self.schema_url}?sha256={self.sha256}"

    @property
    def catalog_url(self) -> str:
        return f"{self.host}/api/v1/catalog/dm/{self.ct_id}/"

    def check(self) -> None:
        if self.jsonld.get("identifier") != self.ct_id:
            raise PackageError(f"package JSON-LD identifier {self.jsonld.get('identifier')!r} is not {self.ct_id!r}")
        if not self.jsonld.get("components"):
            raise PackageError("package JSON-LD has no components")
        if b"<xsd:schema" not in self.xsd_bytes[:4000] and b"<xs:schema" not in self.xsd_bytes[:4000]:
            raise PackageError("package schema is not an XML Schema")
        current = self.versions.get("current_sha256")
        if current and current != self.sha256:
            raise PackageError(f"schema on disk ({self.sha256[:12]}) is not the published current version ({current[:12]})")


def load_package(directory: str | Path, ct_id: str | None = None, host: str = DEFAULT_HOST) -> ModelPackage:
    d = Path(directory)
    if ct_id is None:
        xsds = sorted(d.glob("dm-*.xsd"))
        if len(xsds) != 1:
            raise PackageError(f"{d}: expected one dm-<ct>.xsd, found {len(xsds)}")
        ct_id = xsds[0].stem[3:]
    jsonld_path, xsd_path = d / f"dm-{ct_id}.jsonld", d / f"dm-{ct_id}.xsd"
    for p in (jsonld_path, xsd_path):
        if not p.exists():
            raise PackageError(f"{p} is missing: the writer needs the model's package, not just its identifier")
    pkg = ModelPackage(ct_id=ct_id, jsonld=json.loads(jsonld_path.read_text(encoding="utf-8")), xsd_bytes=xsd_path.read_bytes(),
                       catalog=_optional_json(d / "catalog.json"), versions=_optional_json(d / "versions.json"), host=host)
    pkg.check()
    return pkg


def fetch_package(ct_id: str, save_to: str | Path | None = None, host: str = DEFAULT_HOST, timeout: int = 60) -> ModelPackage:
    """Fetch a published model's package from the public catalog (no account needed) and optionally save it."""
    import requests  # optional dependency

    def get(url, **kw):
        r = requests.get(url, timeout=timeout, **kw)
        if r.status_code != 200:
            raise PackageError(f"{url}: HTTP {r.status_code}")
        return r

    catalog = get(f"{host}/api/v1/catalog/dm/{ct_id}/").json()
    jsonld = get(f"{host}/api/v1/catalog/dm/{ct_id}/jsonld/").json()
    if isinstance(jsonld, dict) and "download_url" in jsonld and "components" not in jsonld:
        # a storage-backed artifact: the catalog answers with a pointer to the file, not the file
        jsonld = get(jsonld["download_url"]).json()
    xsd = get(f"{host}/dmlib/dm-{ct_id}.xsd").content
    versions = get(f"{host}/dmlib/dm-{ct_id}.versions.json").json()
    pkg = ModelPackage(ct_id=ct_id, jsonld=jsonld, xsd_bytes=xsd, catalog=catalog, versions=versions, host=host)
    pkg.check()
    if save_to is not None:
        d = Path(save_to)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"dm-{ct_id}.jsonld").write_text(json.dumps(jsonld, indent=1, ensure_ascii=False), encoding="utf-8")
        (d / f"dm-{ct_id}.xsd").write_bytes(xsd)
        (d / "catalog.json").write_text(json.dumps(catalog, indent=1, ensure_ascii=False), encoding="utf-8")
        (d / "versions.json").write_text(json.dumps(versions, indent=1), encoding="utf-8")
    return pkg


def _optional_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
