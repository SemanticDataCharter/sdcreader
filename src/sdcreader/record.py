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
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .model import LEAF_TYPES, SDC4, Component, Model

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


class RecordError(Exception):
    pass


@dataclass
class ExceptionalValue:
    code: str              # "ASKR"
    name: str              # "Asked and Refused"
    origin: str            # "source": in place of the value; "recovery": beside a value that failed its constraint


@dataclass
class RecordValue:
    component: Component
    path: list[Component]          # the clusters above it, root first
    occurrence: int                # 0 for the first time this component appears under this path, 1 for the next, ...
    position: int                  # document order among the record's values, 0-based
    elements: dict                 # the value elements as the record holds them: name -> text, or name -> dict for a
                                   # nested element (a quantity's units: {"label": "Trade Units", "xdstring-value": "EA"})
    context: dict[str, str]        # act, vtb, vte, tr, modified, latitude, longitude, where present
    exceptional: ExceptionalValue | None = None

    @property
    def rejected(self) -> dict:
        """The value elements a recovery Exceptional Value stands beside: the value that failed its constraint."""
        return self.elements if self.exceptional and self.exceptional.origin == "recovery" else {}


@dataclass
class Record:
    model: Model
    attributes: dict[str, str]
    values: list[RecordValue] = field(default_factory=list)

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


def read_record(source: bytes | str | Path, model: Model) -> Record:
    """Read a Governed Data Record (XML) and join it to the model it names.

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

    record = Record(model=model, attributes=attributes)
    seen: dict[tuple, int] = {}

    def walk(el, path: list[Component]):
        for child in el:
            if not _is_sdc4(child):
                continue
            n = _local(child.tag)
            if not n.startswith("ms-"):
                continue
            comp = model.components.get(n[3:])
            if comp is None:                     # an adapter: pass through to the component inside
                walk(child, path)
            elif comp.sdc_type == "Cluster" or comp.sdc_type not in LEAF_TYPES:
                walk(child, path + [comp])       # a cluster, or a structural component (audit, party, ...) holding values
            else:
                key = (comp.ct_id, tuple(c.ct_id for c in path))
                occurrence = seen.get(key, 0)
                seen[key] = occurrence + 1
                record.values.append(_value(child, comp, path, occurrence, len(record.values)))

    walk(root, [])
    return record


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
        value_present = any(k.endswith("-value") or k.startswith("xdtemporal-") for k in elements)
        exceptional = ExceptionalValue(code=ev_code, name=EXCEPTIONAL_VALUES[ev_code],
                                       origin="recovery" if value_present else "source")
    return RecordValue(component=comp, path=path, occurrence=occurrence, position=position, elements=elements,
                       context=context, exceptional=exceptional)
