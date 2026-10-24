"""The record reader: a Governed Data Record (XML) read and joined to its model.

Fixture: a Credit Note record from HalvorsenDemo and the published package of its model (samples/halvorsen-credit-note).
"""
from pathlib import Path

import pytest
from lxml import etree

from sdcreader import load_package, read_model
from sdcreader.model import SDC4
from sdcreader.record import EXCEPTIONAL_VALUES, RecordError, read_record

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "halvorsen-credit-note"
CT = "jkuyr38hydqaiwlq5vhp2rjr"
RECORD = SAMPLE / "record.xml"


@pytest.fixture(scope="module")
def model():
    return read_model(load_package(SAMPLE, CT))


def _first_string(tree):
    """The first XdString value element in the record, and its component element."""
    value = tree.find(".//xdstring-value")
    return value, value.getparent()


def test_attributes_and_values(model):
    r = read_record(RECORD, model)
    assert r.attributes["dm-label"] == "Credit Note"
    assert r.instance_id == r.attributes["instance_id"] and len(r.instance_id) == 24
    assert r.attributes["instance_version"] == "1"
    assert r.values and all(v.elements or v.exceptional for v in r.values)
    assert [v.position for v in r.values] == list(range(len(r.values)))
    assert all(v.path and v.path[0] is model.root for v in r.values)


def test_every_value_is_a_component_of_the_model_and_adapters_are_passed_through(model):
    r = read_record(RECORD, model)
    assert {v.component.ct_id for v in r.values} <= set(model.components)
    adapters = {el.tag.split("ms-", 1)[1] for el in etree.parse(str(RECORD)).iter(f"{{{SDC4}}}*")
                if el.tag.split("}", 1)[1].startswith("ms-") and el.tag.split("ms-", 1)[1] not in model.components}
    assert adapters, "the fixture should contain adapter elements"
    assert not adapters & {c.ct_id for v in r.values for c in [v.component, *v.path]}


def test_a_quantity_keeps_its_units_nested(model):
    r = read_record(RECORD, model)
    q = next(v for v in r.values if v.component.sdc_type == "XdQuantity")
    assert "xdquantity-value" in q.elements
    units = q.elements["xdquantity-units"]
    assert isinstance(units, dict) and units["xdstring-value"]


def test_the_same_record_as_text_and_bytes(model):
    a = read_record(RECORD, model)
    b = read_record(RECORD.read_bytes(), model)
    c = read_record(RECORD.read_text(encoding="utf-8"), model)
    assert [v.elements for v in a.values] == [v.elements for v in b.values] == [v.elements for v in c.values]


def test_a_record_of_another_model_is_refused(model):
    other = RECORD.read_text(encoding="utf-8").replace(f"dm-{CT}", "dm-" + "a" * 24)
    with pytest.raises(RecordError, match="not " + CT):
        read_record(other, model)


@pytest.mark.parametrize("text, match", [
    ("<notarecord/>", "not an sdc4:dm-"),
    ("<sdc4:dm-x", "not well-formed"),
])
def test_what_is_not_a_record_is_refused(model, text, match):
    with pytest.raises(RecordError, match=match):
        read_record(text, model)


def test_an_exceptional_value_written_at_the_source_stands_in_place_of_the_value(model):
    tree = etree.parse(str(RECORD))
    value, comp = _first_string(tree)
    comp.remove(value)
    ev = etree.SubElement(comp, f"{{{SDC4}}}ASKR")
    etree.SubElement(ev, "ev-name").text = "Asked and Refused"
    comp.insert(1, ev)
    r = read_record(etree.tostring(tree), model)
    v = next(v for v in r.values if v.exceptional)
    assert (v.exceptional.code, v.exceptional.name, v.exceptional.origin) == ("ASKR", "Asked and Refused", "source")
    assert "xdstring-value" not in v.elements and v.rejected == {}
    assert r.exceptional == [v]


def test_an_exceptional_value_from_recovery_stands_beside_the_rejected_value(model):
    tree = etree.parse(str(RECORD))
    value, comp = _first_string(tree)
    ev = etree.Element(f"{{{SDC4}}}INV")
    etree.SubElement(ev, "ev-name").text = "Invalid"
    comp.insert(1, ev)
    r = read_record(etree.tostring(tree), model)
    v = next(v for v in r.values if v.exceptional)
    assert (v.exceptional.code, v.exceptional.origin) == ("INV", "recovery")
    assert v.rejected == {"xdstring-value": value.text}


def test_every_iso_21090_code_is_known():
    assert set(EXCEPTIONAL_VALUES) == {"INV", "OTH", "UNC", "NI", "NA", "UNK", "ASKU", "ASKR", "NASK", "NAV", "MSK",
                                       "DER", "PINF", "NINF", "TRC", "QS"}


def test_a_repeated_component_is_numbered_in_document_order(model):
    tree = etree.parse(str(RECORD))
    _, comp = _first_string(tree)
    twin = etree.fromstring(etree.tostring(comp))
    twin.find("xdstring-value").text = "second"
    comp.addnext(twin)
    r = read_record(etree.tostring(tree), model)
    pair = [v for v in r.values if v.component.ct_id == comp.tag.split("ms-", 1)[1]]
    assert [v.occurrence for v in pair[:2]] == [0, 1]
    assert pair[1].elements["xdstring-value"] == "second"


def test_context_elements_are_kept_apart_from_the_value(model):
    tree = etree.parse(str(RECORD))
    value, comp = _first_string(tree)
    vtb = etree.Element("vtb")
    vtb.text = "2026-01-01T00:00:00"
    value.addprevious(vtb)
    r = read_record(etree.tostring(tree), model)
    v = next(v for v in r.values if v.context)
    assert v.context == {"vtb": "2026-01-01T00:00:00"} and "vtb" not in v.elements


@pytest.mark.parametrize("sdc_type, value_el", [("XdOrdinal", "ordinal"), ("XdLink", "link"), ("XdFile", "uri"),
                                                ("XdInterval", "lower"), ("XdBoolean", "true-value")])
def test_recovery_is_recognized_for_every_value_element(model, sdc_type, value_el):
    """4.3.1: a recovery Exceptional Value beside a value whose element does not end in -value (an ordinal, a link,
    a file, an interval) was read as written at the source, and its rejected value was lost."""
    from sdcreader.record import VALUE_ELEMENTS, _value
    from sdcreader.model import Component
    assert value_el in VALUE_ELEMENTS
    el = etree.Element(f"{{{SDC4}}}ms-x")
    etree.SubElement(el, "label").text = "L"
    etree.SubElement(el, f"{{{SDC4}}}INV").append(etree.Element("ev-name"))
    etree.SubElement(el, value_el).text = "bad"
    comp = Component(ct_id="x", sdc_type=sdc_type, label="L", description="", data_type="", constraints={}, links={})
    v = _value(el, comp, [], 0, 0)
    assert v.exceptional.origin == "recovery" and v.rejected == {value_el: "bad"}
