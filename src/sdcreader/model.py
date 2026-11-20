"""Read a model package into the shape the CDIF emitter needs: the record tree, its leaves in document order with
their path, the enumerations with the definitions and codes the schema carries, the units each quantity takes.

The JSON-LD package carries every component once, with `contains` references; a component composed in several
places (three blood pressure readings sharing one Blood Pressure cluster) is one component with several positions.
The schema carries what the JSON-LD does not: the definition and the code behind each enumerated value.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote

from lxml import etree

from .package import ModelPackage

XSD_NS = "http://www.w3.org/2001/XMLSchema"
DC_NS = "http://purl.org/dc/elements/1.1/"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SDC4 = "https://semanticdatacharter.com/ns/sdc4/"
NS = {"xsd": XSD_NS, "rdfs": RDFS_NS, "rdf": RDF_NS}

LEAF_TYPES = {"XdString", "XdToken", "XdBoolean", "XdLink", "XdFile", "XdOrdinal", "XdCount", "XdQuantity", "XdFloat", "XdDouble",
              "XdTemporal", "XdInterval", "XdStringList", "XdTokenList", "XdDecimalList", "XdIntegerList"}
NUMERIC_TYPES = {"XdCount", "XdQuantity", "XdFloat", "XdDouble", "XdOrdinal"}
QUANTIFIED_TYPES = {"XdCount", "XdQuantity", "XdFloat", "XdDouble"}

IDENTIFIER = "http://purl.org/dc/terms/identifier"
SOURCE = "http://purl.org/dc/terms/source"
PUBLISHER = "http://purl.org/dc/terms/publisher"
EXACT = "http://www.w3.org/2004/02/skos/core#exactMatch"
CLOSE = "http://www.w3.org/2004/02/skos/core#closeMatch"
SEE_ALSO = "http://www.w3.org/2000/01/rdf-schema#seeAlso"
HAS_UNIT = "https://semanticdatacharter.com/ontology/sdc4-meta/hasUnit"


@dataclass
class Code:
    value: str
    iri: str
    definition: str = ""
    defined_by: str = ""


@dataclass
class Component:
    ct_id: str
    sdc_type: str
    label: str
    description: str
    data_type: str
    constraints: dict
    links: dict[str, list[str]]
    contains: list[str] = field(default_factory=list)

    @property
    def iri(self) -> str:
        return f"{SDC4}mc-{self.ct_id}"

    def link(self, predicate: str) -> str | None:
        v = self.links.get(predicate)
        return v[0] if v else None


@dataclass
class Leaf:
    component: Component
    path: list[Component]          # the clusters above it, root first
    position: int                  # document order, 0-based
    roles: tuple[str, ...] = ()    # parallel to `path`: the reference-model element each step stands in ("party-details",
                                   # "performer"), "" for a component element; empty for the data cluster's leaves (4.5.0)
    role: str = ""                 # the reference-model element the leaf stands in ("function", "start"), "" for a component

    @property
    def slug(self) -> str:
        return "/".join(_slug(c.label) for c in self.path[1:] + [self.component])


#: SDCStudio's field defaults, present in every schema header whether or not the modeler wrote anything; treated as
#: unset so a writer never publishes "Universal" as a geographic coverage or "None" as a relation.
DC_DEFAULTS = {"coverage": {"Universal"}, "relation": {"None"}, "type": {"SDC Data Model (DM)"}}


@dataclass
class Model:
    package: ModelPackage
    title: str
    description: str
    metadata: dict          # the JSON-LD package's metadata (dc:title, dc:creator, dc:rights, dc:date, ...)
    header: dict            # the schema header's Dublin Core, complete: dc:subject, dc:coverage, dc:publisher, dc:contributor, ...

    def dc(self, name: str) -> str | None:
        """A Dublin Core value the modeler wrote: the schema header first, the JSON-LD second, defaults and blanks as None."""
        v = self.header.get(name)
        if v is None:
            v = self.metadata.get(f"dc:{name}")
        if isinstance(v, list):
            v = v[0] if v else None
        v = (v or "").strip() if isinstance(v, str) else v
        if not v or v in DC_DEFAULTS.get(name, set()):
            return None
        return v

    @property
    def contributors(self) -> list[str]:
        v = self.header.get("contributor")
        if v is None:
            v = self.metadata.get("dc:contributor") or []
        return [c.strip() for c in (v if isinstance(v, list) else [v]) if c and c.strip()]

    @property
    def subjects(self) -> list[str]:
        """dc:subject as SDCStudio asks for it: a semicolon-separated list of keywords."""
        v = self.dc("subject") or ""
        return [w.strip() for w in v.split(";") if w.strip()]

    @property
    def rights_url(self) -> str:
        m = re.search(r"https?://\S+", self.dc("rights") or "")
        return m.group(0).rstrip(".,;") if m else ""

    @property
    def rights_statement(self) -> str:
        """The rights text with its URL removed; empty when nothing but a label is left."""
        text = re.sub(r"https?://\S+", "", self.dc("rights") or "").strip(" ,;:")
        return text if len(text) > 12 else ""
    root: Component
    components: dict[str, Component]
    leaves: list[Leaf]
    codes: dict[str, list[Code]]   # component ct_id -> enumerated values with their definitions and codes
    slots: dict[str, dict[str, str]] = field(default_factory=dict)
    """The reference-model elements the schema declares (4.5.0), by owner: the model's own ct_id for the DM's elements
    (subject, provider, protocol, workflow, acs, attestation), a Party's, Participation's, Attestation's or Audit's
    ct_id for its elements (party-details, performer, function, reason, committer, start, ...). Each names the
    component its type is (`"k2ph54lwfdtlrm7p5gw4s3tt"`) or, where the schema leaves the reference model's own type,
    that type (`"sdc4:PartyType"`, `"xsd:dateTime"`)."""

    @property
    def ct_id(self) -> str:
        return self.package.ct_id

    def slot_component(self, owner: str, slot: str) -> Component | None:
        """The component the schema types a reference-model element by, or None where it leaves the reference model's
        own type (SDCStudio declares a DM's subject, provider and attestation as `sdc4:PartyType` and
        `sdc4:AttestationType`; the record's label then says which component it is)."""
        return self.components.get(self.slots.get(owner, {}).get(slot, ""))

    @property
    def placed(self) -> set[str]:
        """Every component the schema places in a reference-model element: a Participation's performer, an
        Attestation's committer, a Party's details cluster, the DM's workflow."""
        return {t for owner in self.slots.values() for t in owner.values() if t in self.components}

    @property
    def unplaced_parties(self) -> list[Component]:
        """The Party components no reference-model element's type names: those the record's subject and provider
        elements, declared as the reference model's `PartyType`, can be. The record's label says which."""
        placed = self.placed
        return [c for c in self.components.values() if c.sdc_type == "Party" and c.ct_id not in placed]

    def part_leaves(self) -> list[Leaf]:
        """The leaves of the reference-model parts beyond the data cluster (4.5.0), in schema order: each Party's,
        Participation's, Attestation's and Audit's elements and its details or location cluster, and the DM's workflow,
        protocol and acs where the schema types them. A part's path starts at its own component; `roles` names the
        reference-model element each step stands in. Parties the schema places nowhere (`unplaced_parties`) are listed
        at the top, since a record's subject or provider can be any of them; a Party placed in a Participation or an
        Attestation is listed inside it. Elements of the reference model's own simple types (a Participation's start,
        an Attestation's pending) are leaves of the component `rm_component` makes for them."""
        out: list[Leaf] = []

        def cluster(c: Component, path: list[Component], roles: tuple[str, ...]):
            for m in c.contains:
                child = self.components[m]
                if child.sdc_type == "Cluster":
                    cluster(child, path + [child], roles + ("",))
                elif child.sdc_type in LEAF_TYPES:
                    out.append(Leaf(component=child, path=path, position=len(out), roles=roles))

        def part(c: Component, path: list[Component], roles: tuple[str, ...]):
            slots = RM_SLOTS.get(c.sdc_type)
            if slots is None:                      # a cluster
                cluster(c, path, roles)
                return
            for name, kind in slots.items():
                declared = self.slots.get(c.ct_id, {}).get(name)
                if declared is None:
                    continue
                comp = self.components.get(declared)
                if kind in STRUCTURAL:
                    if comp is not None:
                        part(comp, path + [comp], roles + (name,))
                    continue
                comp = comp or rm_component(name, kind)
                out.append(Leaf(component=comp, path=path, position=len(out), roles=roles, role=name))

        for c in self.unplaced_parties:
            part(c, [c], ("",))
        for c in self.components.values():
            if c.sdc_type in ("Participation", "Audit", "Attestation") and c.ct_id not in self.placed:
                part(c, [c], ("",))
        dm = self.slots.get(self.ct_id, {})
        for name in ("protocol", "workflow", "acs"):
            comp = self.components.get(dm.get(name, ""))
            if comp is None:
                continue
            if comp.sdc_type == "Cluster":
                cluster(comp, [comp], (name,))
            else:
                out.append(Leaf(component=comp, path=[], position=len(out), role=name))
        return out


#: The reference model's elements a reader reads beyond a component's label, by the SDC4 RM type that owns them, with
#: the kind of each: a reference-model type (Party, Cluster, Attestation, XdString, ...) or a simple type (string,
#: dateTime, boolean). From sdc4.xsd: DMType, PartyType, ParticipationType, AttestationType and AuditType. The DM's
#: Participations, Audits and links are `sdc4:ms-<ct_id>` elements of their own components, not named elements.
RM_SLOTS: dict[str, dict[str, str]] = {
    "DM": {"subject": "Party", "provider": "Party", "protocol": "XdString", "workflow": "Cluster", "acs": "XdLink",
           "attestation": "Attestation"},
    "Party": {"party-name": "string", "party-ref": "XdLink", "party-details": "Cluster"},
    "Participation": {"performer": "Party", "function": "XdString", "mode": "XdString", "start": "dateTime", "end": "dateTime"},
    "Attestation": {"view": "XdFile", "proof": "XdFile", "reason": "XdString", "committer": "Party", "committed": "dateTime",
                    "pending": "boolean"},
    "Audit": {"system-id": "XdString", "system-user": "Party", "location": "Cluster", "timestamp": "dateTime"},
}
#: The kinds that hold further elements rather than a value.
STRUCTURAL = frozenset({"Party", "Cluster", "Attestation"})
#: A simple-typed reference-model element read as the value type that holds the same thing, and that type's element.
SIMPLE_KINDS = {"string": ("XdString", "xdstring-value"), "dateTime": ("XdTemporal", "xdtemporal-datetime"),
                "boolean": ("XdBoolean", None)}
#: Every reference-model element name in RM_SLOTS: the names a mapping rule may use for them.
RM_PARTS = frozenset(n for slots in RM_SLOTS.values() for n, k in slots.items() if k in STRUCTURAL)
RM_ELEMENTS = frozenset(n for slots in RM_SLOTS.values() for n, k in slots.items() if k not in STRUCTURAL)


def rm_component(name: str, kind: str, label: str = "") -> Component:
    """The component a reader gives a reference-model element the schema types by no component of the model: its
    `ct_id` is the element's name (never a CUID2, which is 24 or more characters), its type the reference model's, or,
    for a simple-typed element, the value type that holds the same thing (an `xsd:dateTime` start is an XdTemporal)."""
    sdc_type = SIMPLE_KINDS[kind][0] if kind in SIMPLE_KINDS else kind
    return Component(ct_id=name, sdc_type=sdc_type, label=label or name, description="", data_type="", constraints={}, links={})


def read_model(pkg: ModelPackage) -> Model:
    d = pkg.jsonld
    comps: dict[str, Component] = {}
    for n in d["components"]:
        ct = n["@id"].split("mc-", 1)[1]
        links: dict[str, list[str]] = {}
        for l in n.get("semanticLinks") or []:
            links.setdefault(l["predicate"], []).append(l["object"])
        comps[ct] = Component(ct_id=ct, sdc_type=n["@type"][:-4] if n["@type"].endswith("Type") else n["@type"], label=n["label"],
                              description=n.get("description") or "", data_type=n.get("dataType") or "", constraints=n.get("constraints") or {},
                              links=links, contains=[m["@id"].split("mc-", 1)[1] for m in n.get("contains") or []])
    slots, data_cluster = _slots(pkg.xsd_bytes, pkg.ct_id)
    root = comps[data_cluster] if data_cluster in comps and comps[data_cluster].sdc_type == "Cluster" else _root(comps)
    leaves: list[Leaf] = []

    def walk(c: Component, path: list[Component]):
        for m in c.contains:
            child = comps[m]
            if child.sdc_type == "Cluster":
                walk(child, path + [child])
            elif child.sdc_type in LEAF_TYPES:
                leaves.append(Leaf(component=child, path=path + [c] if c is not path[-1] else path, position=len(leaves)))

    walk(root, [root])
    return Model(package=pkg, title=d.get("label") or d["metadata"].get("dc:title", ""), description=d.get("description") or "",
                 metadata=d.get("metadata") or {}, header=read_header(pkg.xsd_bytes), root=root, components=comps, leaves=leaves,
                 codes=_codes(pkg.xsd_bytes), slots=slots)


#: The reference-model base types whose named elements `Model.slots` reads.
_RM_BASES = {"sdc4:DMType": "DM", "sdc4:PartyType": "Party", "sdc4:ParticipationType": "Participation",
             "sdc4:AttestationType": "Attestation", "sdc4:AuditType": "Audit"}


def _slots(xsd_bytes: bytes, ct_id: str) -> tuple[dict[str, dict[str, str]], str | None]:
    """The reference-model elements each DM, Party, Participation, Attestation and Audit complexType declares, and the
    DM's data cluster (the `sdc4:ms-<ct_id>` its complexType refers to first)."""
    tree = etree.fromstring(xsd_bytes)
    out: dict[str, dict[str, str]] = {}
    data_cluster = None
    for ct in tree.iterfind(f"{{{XSD_NS}}}complexType"):
        name = ct.get("name") or ""
        if not name.startswith("mc-"):
            continue
        r = ct.find(f"{{{XSD_NS}}}complexContent/{{{XSD_NS}}}restriction")
        kind = _RM_BASES.get(r.get("base") if r is not None else "")
        if kind is None:
            continue
        declared: dict[str, str] = {}
        for el in r.iterfind(f"{{{XSD_NS}}}sequence/{{{XSD_NS}}}element"):
            ref = el.get("ref") or ""
            if kind == "DM" and name[3:] == ct_id and data_cluster is None and ref.startswith("sdc4:ms-"):
                data_cluster = ref.split("ms-", 1)[1]
            el_name = el.get("name")
            if el_name not in RM_SLOTS[kind]:
                continue
            t = el.get("type") or ""
            declared[el_name] = t.split("mc-", 1)[1] if t.startswith("sdc4:mc-") else t
        out[name[3:]] = declared
    return out, data_cluster


def read_header(xsd_bytes: bytes) -> dict:
    """The Dublin Core the schema header carries for the model (the first rdf:Description with dc: children): every
    field the modeler could fill, blanks included, contributors as a list."""
    tree = etree.fromstring(xsd_bytes)
    out: dict = {}
    for desc in tree.iter(f"{{{RDF_NS}}}Description"):
        dc = [el for el in desc if isinstance(el.tag, str) and el.tag.startswith(f"{{{DC_NS}}}")]
        if not dc:
            continue
        for el in dc:
            name = el.tag.split("}", 1)[1]
            text = " ".join((el.text or "").split())
            if name == "contributor":
                out.setdefault("contributor", []).append(text)
            else:
                out[name] = text
        break
    return out


def _root(comps: dict[str, Component]) -> Component:
    contained = {m for c in comps.values() for m in c.contains}
    roots = [c for c in comps.values() if c.sdc_type == "Cluster" and c.ct_id not in contained and c.contains]
    # the governed record is the cluster that contains the others; a party or audit detail cluster also sits uncontained
    roots.sort(key=lambda c: -_size(c, comps))
    if not roots:
        raise ValueError("no root cluster in the package")
    return roots[0]


def _size(c: Component, comps: dict[str, Component]) -> int:
    return 1 + sum(_size(comps[m], comps) for m in c.contains)


def _codes(xsd_bytes: bytes) -> dict[str, list[Code]]:
    """The enumerated values of every component, with the definition and the code the schema annotates them with."""
    tree = etree.fromstring(xsd_bytes)
    out: dict[str, list[Code]] = {}
    for ct in tree.iterfind(f"{{{XSD_NS}}}complexType"):
        name = ct.get("name") or ""
        if not name.startswith("mc-"):
            continue
        codes: list[Code] = []
        for enum in ct.iterfind(f".//{{{XSD_NS}}}enumeration"):
            value = enum.get("value")
            doc = enum.find(f"{{{XSD_NS}}}annotation/{{{XSD_NS}}}documentation")
            cls = enum.find(f"{{{XSD_NS}}}annotation/{{{XSD_NS}}}appinfo/{{{RDFS_NS}}}Class")
            iri = cls.get(f"{{{RDF_NS}}}about") if cls is not None else ""
            defined_by = ""
            if cls is not None:
                db = cls.find(f"{{{RDFS_NS}}}isDefinedBy")
                if db is not None:
                    defined_by = (db.get(f"{{{RDF_NS}}}resource") or (db.text or "")).strip()
            codes.append(Code(value=value, iri=iri or "", definition=" ".join((doc.text or "").split()) if doc is not None else "", defined_by=defined_by))
        if codes:
            out[name[3:]] = codes
    return out


def _slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return s or "x"


def enumeration_iri(component: Component, codes: list[Code]) -> str:
    """The IRI of a component's value set: the parent of the per-value class IRIs the schema declares."""
    for c in codes:
        if c.iri:
            return c.iri.rsplit("/", 1)[0]
    return f"{component.iri}/{component.sdc_type.lower()}-value"
