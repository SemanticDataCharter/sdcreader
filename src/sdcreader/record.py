"""Read a Governed Data Record (the XML instance) and join each value to the model component that defines it.

A record's root is `sdc4:dm-<ct_id>`, carrying the record's own attributes (`instance_id`, `instance_version`,
`creation_timestamp`, `current-state`, ...). Below it, every component appears as an `sdc4:ms-<ct_id>` element. A
cluster's members sit inside adapter elements, also named `sdc4:ms-<ct_id>` but not components of the model; the
reader passes through them. A data-bearing component holds its label, its per-value context (`act`, `vtb`, `vte`, `tr`,
`modified`, `latitude`, `longitude`), its value elements (`xdstring-value`, `xdquantity-value` with
`xdquantity-units`, `xdtemporal-datetime`, ...) and, where the value is missing or unusable, an Exceptional Value: an
`sdc4:<code>` element with the ISO 21090 null flavor code (`sdc4:ASKR`, `sdc4:INV`, ...) and its `ev-name`.

An Exceptional Value written where the record was made stands in place of the value. One inserted by recovery
(sdcvalidator's `validate_with_recovery`, which tags the record `valid_with_ev`) stands beside the value that failed
its constraint, which stays in the record; the reader keeps that value, marked as rejected.

The reader keeps every value element's text as the record holds it. It does not type values, validate them or know
any target; that is the reader's caller's work.

Since 4.5.0, `read_record(..., reference_model=True)` also reads the reference-model parts beyond the data cluster:
the DM's subject and providers (Parties), its Participations (performer, function, mode, start, end), protocol,
workflow, acs, Audits (system-id, system-user, location, timestamp) and attestation (view, proof, reason, committer,
committed, pending), and every Party's name, reference and details cluster. These are named elements of the reference
model (`<subject>`, `<performer>`, `<party-details>`), not `sdc4:ms-<ct_id>` elements, so a value inside them is read
against the component the schema types the element by (a Participation's performer, a Party's details cluster), or,
where the schema leaves the reference model's own type, the component the record's label names (SDCStudio declares
the DM's subject, provider and attestation as `sdc4:PartyType` and `sdc4:AttestationType`). Where neither names one,
the reader makes a component for the element (`sdcreader.model.rm_component`) whose ct_id is the element's name. Each
value's `roles` say which reference-model element each step of its path stands in, so a caller tells the subject's
details from the provider's even where both use one Party component. Without `reference_model` the reader reads
exactly what 4.4 read.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .model import LEAF_TYPES, RM_SLOTS, SDC4, SIMPLE_KINDS, STRUCTURAL, Component, Model, rm_component

#: ISO 21090 null flavors, as the SDC4 reference model names its Exceptional Value elements.
EXCEPTIONAL_VALUES = {
    "INV": "Invalid", "OTH": "Other", "UNC": "Unencoded", "NI": "No Information", "NA": "Not Applicable",
    "UNK": "Unknown", "ASKU": "Asked but Unknown", "ASKR": "Asked and Refused", "NASK": "Not Asked",
    "NAV": "Not Available", "MSK": "Masked", "DER": "Derived", "PINF": "Positive Infinity",
    "NINF": "Negative Infinity", "TRC": "Trace", "QS": "Sufficient Quantity",
}

#: The record attributes a Governed Data Record carries under its root, by element name.
RECORD_ATTRIBUTES = ("dm-label", "dm-language", "dm-encoding", "creation_timestamp", "instance_id", "instance_version",
                     "source_instance_id", "source_version_id", "current-state")

#: Per-value context elements: what the record says about a value rather than the value itself.
CONTEXT_ELEMENTS = ("act", "vtb", "vte", "tr", "modified", "latitude", "longitude")

#: The elements that hold a value, by the SDC4 reference model (sdc4.xsd), for every value type. A recovery Exceptional
#: Value stands beside one of these; one written at the source stands in place of them. Units, language, magnitude
#: status, accuracy, reference ranges and a link's relation describe a value and are not in this set.
VALUE_ELEMENTS = frozenset({
    "xdstring-value", "xdtoken-value", "true-value", "false-value",
    "xdcount-value", "xdquantity-value", "xdfloat-value", "xddouble-value",
    "xdtemporal-date", "xdtemporal-time", "xdtemporal-datetime", "xdtemporal-duration", "xdtemporal-year",
    "xdtemporal-year-month", "xdtemporal-month", "xdtemporal-month-day", "xdtemporal-day",
    "ordinal", "symbol", "link", "uri", "media-content", "lower", "upper",
    "xdstringlist-value", "xdtokenlist-value", "xddecimallist-value", "xdintegerlist-value",
})


class RecordError(Exception):
    pass


@dataclass
class ExceptionalValue:
    code: str              # "ASKR"
    name: str              # "Asked and Refused"
    origin: str            # "source": in place of the value; "recovery": beside a value that failed its constraint.
                           # Inferred from the record's shape, so a best guess: a published model may require the
                           # value element (SDCStudio's generated schemas do, though the reference model leaves it
                           # optional), and then a source Exceptional Value sits beside a value too. Whoever inserted
                           # Exceptional Values (a validator's recovery) knows the origin for certain.


@dataclass
class RecordValue:
    component: Component
    path: list[Component]          # the clusters above it, root first
    occurrence: int                # 0 for the first time this component appears in its cluster instance, 1 for the next
    position: int                  # document order among the record's values, 0-based
    elements: dict                 # the value elements as the record holds them: name -> text, or name -> dict for a
                                   # nested element (a quantity's units: {"label": "Trade Units", "xdstring-value": "EA"})
    context: dict[str, str]        # act, vtb, vte, tr, modified, latitude, longitude, where present
    exceptional: ExceptionalValue | None = None
    instances: tuple[int, ...] = ()   # parallel to `path`: which occurrence each cluster is among the same cluster's
                                      # repeats under the same parent instance (4.4.0). Two lines of one Line cluster
                                      # in one Lines cluster are (..., 0) and (..., 1).
    roles: tuple[str, ...] = ()       # parallel to `path`: the reference-model element each step stands in ("subject",
                                      # "party-details", "performer"), "" for an sdc4:ms-<ct_id> element (4.5.0)
    role: str = ""                    # the reference-model element the value stands in ("function", "start",
                                      # "party-name"), "" for an sdc4:ms-<ct_id> element (4.5.0)

    @property
    def instance_key(self) -> tuple[tuple[str, int], ...]:
        """The value's cluster instance, root first: (ct_id, occurrence) for every cluster above it. Values with equal
        keys belong to the same cluster instance; a mapper writes one target element per key."""
        return tuple(zip((c.ct_id for c in self.path), self.instances))

    @property
    def rejected(self) -> dict:
        """The value elements a recovery Exceptional Value stands beside: the value that failed its constraint."""
        return self.elements if self.exceptional and self.exceptional.origin == "recovery" else {}


@dataclass
class Record:
    model: Model
    attributes: dict[str, str]
    values: list[RecordValue] = field(default_factory=list)
    reference_model: bool = False     # read with the reference-model parts beyond the data cluster (4.5.0)

    @property
    def parts(self) -> list[RecordValue]:
        """The values read from the reference-model parts beyond the data cluster (4.5.0): those under a named
        reference-model element, or one themselves."""
        return [v for v in self.values if v.role or any(v.roles)]

    @property
    def instance_id(self) -> str:
        return self.attributes.get("instance_id", "")

    @property
    def exceptional(self) -> list[RecordValue]:
        return [v for v in self.values if v.exceptional]


def _local(tag) -> str:
    return tag.split("}", 1)[1] if isinstance(tag, str) and "}" in tag else (tag if isinstance(tag, str) else "")


def _is_sdc4(el) -> bool:
    return isinstance(el.tag, str) and el.tag.startswith(f"{{{SDC4}}}")


def _text(el) -> str:
    return (el.text or "").strip()


def _nested(el) -> dict | str:
    """An element's content: its text if it has no element children, else a dict of its children's content."""
    kids = [c for c in el if isinstance(c.tag, str)]
    if not kids:
        return _text(el)
    return {_local(c.tag): _nested(c) for c in kids}


def read_record(source: bytes | str | Path, model: Model, reference_model: bool = False) -> Record:
    """Read a Governed Data Record (XML) and join it to the model it names.

    With `reference_model`, also read the reference-model parts beyond the data cluster (see the module's docstring).

    `source` is the record's bytes, its text, or a path to it. The record's root must be `sdc4:dm-<ct_id>` for the
    model's ct_id; a record of another model is refused rather than read against the wrong definitions.
    """
    if isinstance(source, Path) or (isinstance(source, str) and not source.lstrip().startswith("<")):
        data = Path(source).read_bytes()
    else:
        data = source.encode("utf-8") if isinstance(source, str) else source
    try:
        root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as e:
        raise RecordError(f"the record is not well-formed XML: {e}") from e

    name = _local(root.tag)
    if not (_is_sdc4(root) and name.startswith("dm-")):
        raise RecordError(f"the record's root is {root.tag!r}, not an sdc4:dm-<ct_id> element")
    if name[3:] != model.ct_id:
        raise RecordError(f"the record is of model {name[3:]}, not {model.ct_id}")

    attributes = {}
    for el in root:
        n = _local(el.tag)
        if n in RECORD_ATTRIBUTES:
            attributes[n] = _text(el)

    record = Record(model=model, attributes=attributes, reference_model=reference_model)
    for el, comp, path, roles, instances, occurrence, role, simple in walk_values(root, model, reference_model):
        if simple:
            v = _simple(el, comp, path, occurrence, len(record.values))
        else:
            v = _value(el, comp, path, occurrence, len(record.values))
        v.instances, v.roles, v.role = instances, roles, role
        record.values.append(v)
    return record


def _label(el) -> str:
    for c in el:
        if _local(c.tag) == "label":
            return _text(c)
    return ""


def walk_values(root, model: Model, reference_model: bool = False):
    """Every value element of a record, in document order, as the reader numbers them: (element, component, path,
    roles, instances, occurrence, role, simple), `simple` for a reference-model element of a simple type (a
    Participation's start) rather than a value type. `read_record` reads these; a caller holding the record's tree (a validation
    gate placing the Exceptional Values it inserted) numbers its elements by them. Works on lxml and ElementTree."""
    seen: dict[tuple, int] = {}       # leaf occurrences, per cluster instance
    clusters: dict[tuple, int] = {}   # cluster occurrences, per parent cluster instance
    made: dict[tuple, Component] = {}  # components made for reference-model elements the schema types by none

    def slot_component(owner_ct: str, name: str, kind: str, el) -> Component:
        declared = model.slots.get(owner_ct, {}).get(name, "")
        comp = model.components.get(declared)
        if comp is not None:
            return comp
        label = _label(el)
        if kind in ("Party", "Attestation", "Cluster") and label:
            found = [c for c in model.components.values() if c.sdc_type == kind and c.label == label]
            if len(found) > 1 and kind == "Party":
                placed = model.placed
                found = [c for c in found if c.ct_id not in placed] or found
            if len(found) > 1 and kind == "Party":
                details = next((c for c in el if _local(c.tag) == "party-details"), None)
                dl = _label(details) if details is not None else ""
                found = [c for c in found if (d := model.slot_component(c.ct_id, "party-details")) is not None and d.label == dl] or found
            if len(found) > 1 and kind == "Cluster":
                members = {_local(c.tag)[3:] for c in el if _is_sdc4(c) and _local(c.tag).startswith("ms-")}
                found = [c for c in found if members <= set(c.contains)] or found
            if len(found) == 1:
                return found[0]
        key = (name, kind, label)
        if key not in made:
            made[key] = rm_component(name, kind, label)
        return made[key]

    def walk(el, path: list[Component], instances: tuple[int, ...], roles: tuple[str, ...], owner_type: str, owner_ct: str):
        parent = tuple(zip((c.ct_id for c in path), instances))
        for child in el:
            if not isinstance(child.tag, str):
                continue
            n = _local(child.tag)
            if _is_sdc4(child):
                if not n.startswith("ms-"):
                    continue
                comp = model.components.get(n[3:])
                if comp is None:                     # an adapter: pass through to the component inside
                    yield from walk(child, path, instances, roles, owner_type, owner_ct)
                elif comp.sdc_type == "Cluster" or comp.sdc_type not in LEAF_TYPES:
                    key = (parent, comp.ct_id)       # a cluster, or a structural component (audit, party, ...) holding values
                    k = clusters.get(key, 0)
                    clusters[key] = k + 1
                    yield from walk(child, path + [comp], instances + (k,), roles + ("",), comp.sdc_type, comp.ct_id)
                else:
                    key = (comp.ct_id, parent)
                    occurrence = seen.get(key, 0)
                    seen[key] = occurrence + 1
                    yield child, comp, path, roles, instances, occurrence, "", False
                continue
            # a named reference-model element: read only when asked, and only where the reference model puts it
            kind = RM_SLOTS.get(owner_type, {}).get(n) if reference_model and "}" not in child.tag else None
            if kind is None:
                continue
            comp = slot_component(owner_ct, n, kind, child)
            if kind in STRUCTURAL:
                key = (parent, comp.ct_id)
                k = clusters.get(key, 0)
                clusters[key] = k + 1
                yield from walk(child, path + [comp], instances + (k,), roles + (n,), kind, comp.ct_id)
            else:
                key = (comp.ct_id, parent)
                occurrence = seen.get(key, 0)
                seen[key] = occurrence + 1
                yield child, comp, path, roles, instances, occurrence, n, kind in SIMPLE_KINDS

    yield from walk(root, [], (), (), "DM", model.ct_id)


def _simple(el, comp: Component, path: list[Component], occurrence: int, position: int) -> RecordValue:
    """A reference-model element of a simple type (a Participation's start, an Attestation's pending, a Party's name),
    read as the value type that holds the same thing: its text in that type's value element."""
    text = _text(el)
    if comp.sdc_type == "XdBoolean":
        elements = {"true-value" if text in ("true", "1") else "false-value": text}
    else:
        elements = {next(v for t, v in SIMPLE_KINDS.values() if t == comp.sdc_type): text}
    return RecordValue(component=comp, path=path, occurrence=occurrence, position=position, elements=elements, context={})


def _value(el, comp: Component, path: list[Component], occurrence: int, position: int) -> RecordValue:
    elements: dict = {}
    context: dict[str, str] = {}
    ev_code = None
    for c in el:
        if not isinstance(c.tag, str):
            continue
        n = _local(c.tag)
        if _is_sdc4(c) and n in EXCEPTIONAL_VALUES:
            ev_code = n
        elif n == "label":
            continue
        elif n in CONTEXT_ELEMENTS:
            context[n] = _text(c)
        else:
            elements[n] = _nested(c)
    exceptional = None
    if ev_code:
        value_present = any(k in VALUE_ELEMENTS for k in elements)
        exceptional = ExceptionalValue(code=ev_code, name=EXCEPTIONAL_VALUES[ev_code],
                                       origin="recovery" if value_present else "source")
    return RecordValue(component=comp, path=path, occurrence=occurrence, position=position, elements=elements,
                       context=context, exceptional=exceptional)
