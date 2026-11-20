"""The reference-model parts beyond the data cluster (4.5.0): the model's slots and the record's subject, providers,
Participations, workflow and attestation.

Fixtures: SDCHealth's Laboratory Report (production, public) and two synthetic records of it, one with an Exceptional
Value in the subject's details (samples/sdchealth-lab-report); the HalvorsenDemo Credit Note and the NHANES Participant,
whose subject and provider carry only a name.
"""
from pathlib import Path

import pytest
from lxml import etree

from sdcreader import load_package, read_model, read_record
from sdcreader.model import RM_ELEMENTS, RM_PARTS, RM_SLOTS, SDC4
from sdcreader.record import walk_values

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
LAB = SAMPLES / "sdchealth-lab-report"
LAB_RECORD = LAB / "records" / "labrep00synthxxxxxxxxxxx.xml"
LAB_EV = LAB / "records" / "labrep05synthxxxxxxxxxxx.xml"
CREDIT = SAMPLES / "halvorsen-credit-note"

DATA_CLUSTER = "qnocwj0gevwczd88of20iucv"
PATIENT, AUTHOR = "uficdtk6vpsgvpeyr1sevj9j", "qau8mx32a2d0v54jrc2q7y9y"
PATIENT_DETAILS, PROFESSIONAL = "k2ph54lwfdtlrm7p5gw4s3tt", "geuvvqy9qol4t10s231a4ezo"
ATTESTER_PARTICIPATION, ATTESTER, ATTESTER_FUNCTION = "e7jes8an7n8t58qyabk1nnm2", "p85634qf42iq66vkrcd3mrtd", "z0gm7qs3bvdt2s1tie2gcrue"
LEGAL_AUTHENTICATION, LEGAL_AUTHENTICATOR, REASON = "q1yia3n12i53ly5mdjldocw9", "j9hm5g071ymwa2vau6kb3jh4", "scp5mi7ynr4x0g1zo1p6h9jc"
WORKFLOW = "n92zyhs2luqrhr4hw483kh6m"
GIVEN_NAME = "l9l169co9r23e6fftpvdz4e3"


@pytest.fixture(scope="module")
def lab():
    return read_model(load_package(LAB))


@pytest.fixture(scope="module")
def parts(lab):
    return read_record(LAB_RECORD, lab, reference_model=True)


def test_the_root_is_the_data_cluster_the_dm_names(lab):
    # 4.4 took the largest uncontained cluster, which in this model is the Patient's details cluster
    assert lab.root.ct_id == DATA_CLUSTER


def test_the_schema_slots_name_the_components_the_generated_schema_types_them_by(lab):
    dm = lab.slots[lab.ct_id]
    assert dm["subject"] == "sdc4:PartyType" and dm["provider"] == "sdc4:PartyType"   # SDCStudio leaves these base
    assert dm["attestation"] == "sdc4:AttestationType" and dm["workflow"] == WORKFLOW
    assert lab.slots[PATIENT] == {"party-details": PATIENT_DETAILS}
    assert lab.slots[ATTESTER_PARTICIPATION] == {"performer": ATTESTER, "function": ATTESTER_FUNCTION,
                                                  "start": "xsd:dateTime", "end": "xsd:dateTime"}
    assert lab.slots[LEGAL_AUTHENTICATION]["committer"] == LEGAL_AUTHENTICATOR
    assert lab.slot_component(ATTESTER_PARTICIPATION, "performer").label == "Attester"
    assert lab.slot_component(lab.ct_id, "subject") is None
    assert {c.ct_id for c in lab.unplaced_parties} == {PATIENT, AUTHOR}


def test_part_leaves_reach_every_party_details_leaf(lab):
    leaves = lab.part_leaves()
    patient = [l for l in leaves if l.path[0].ct_id == PATIENT]
    assert patient and all(l.roles[:2] == ("", "party-details") for l in patient)
    assert any(l.component.ct_id == GIVEN_NAME for l in patient)
    start = next(l for l in leaves if l.path[0].ct_id == ATTESTER_PARTICIPATION and l.role == "start")
    assert start.component.ct_id == "start" and start.component.sdc_type == "XdTemporal"
    assert any(l.role == "function" and l.component.ct_id == ATTESTER_FUNCTION for l in leaves)
    assert any(l.roles and l.roles[0] == "workflow" for l in leaves)


def test_without_the_flag_the_record_reads_as_before(lab):
    r = read_record(LAB_RECORD, lab)
    assert not r.reference_model and not r.parts
    assert all(v.path and v.path[0].ct_id == DATA_CLUSTER for v in r.values)
    assert all(not any(v.roles) and not v.role for v in r.values)


def test_the_data_cluster_values_are_unchanged_by_the_flag(lab, parts):
    plain = read_record(LAB_RECORD, lab)
    n = len(plain.values)
    assert [(v.component.ct_id, v.elements, v.position, v.instances) for v in plain.values] == \
           [(v.component.ct_id, v.elements, v.position, v.instances) for v in parts.values[:n]]
    assert len(parts.parts) == len(parts.values) - n


def test_every_value_in_the_record_is_read(lab):
    """Every text-bearing element below the root (labels, Exceptional Value names and the record's attributes aside)
    sits inside a value the reader gives."""
    for f in (LAB_RECORD, LAB_EV):
        tree = etree.parse(str(f))
        root = tree.getroot()
        read = {tree.getpath(t[0]) for t in walk_values(root, lab, reference_model=True)}
        for el in root.iter():
            if not isinstance(el.tag, str) or len(el) or not (el.text or "").strip() or el.getparent() is root:
                continue
            if etree.QName(el).localname in ("label", "ev-name"):
                continue
            p = tree.getpath(el)
            assert any(p == v or p.startswith(v + "/") for v in read), p


def test_subject_and_provider_are_their_party_components_by_label(parts):
    subject = [v for v in parts.parts if v.roles[:1] == ("subject",)]
    provider = [v for v in parts.parts if v.roles[:1] == ("provider",)]
    assert {v.path[0].ct_id for v in subject} == {PATIENT}
    assert {v.path[0].ct_id for v in provider} == {AUTHOR}
    assert {v.path[1].ct_id for v in subject} == {PATIENT_DETAILS}
    assert {v.path[1].ct_id for v in provider} == {PROFESSIONAL}
    assert all(v.roles[1] == "party-details" for v in subject + provider)
    assert [v.elements["xdstring-value"] for v in subject if v.component.ct_id == GIVEN_NAME] == ["Ana"]
    assert [v.elements["xdstring-value"] for v in provider if v.component.ct_id == GIVEN_NAME] == ["Elena"]


def test_a_participation_reads_its_performer_function_and_times(parts):
    att = [v for v in parts.parts if v.path and v.path[0].ct_id == ATTESTER_PARTICIPATION]
    function = next(v for v in att if v.role == "function")
    assert function.component.ct_id == ATTESTER_FUNCTION and function.elements["xdstring-value"] == "attester"
    start = next(v for v in att if v.role == "start")
    assert start.component.ct_id == "start" and start.component.sdc_type == "XdTemporal"
    assert start.elements == {"xdtemporal-datetime": "2026-10-01T09:00:00+01:00"}
    performer = [v for v in att if v.roles[1:2] == ("performer",)]
    assert performer and {v.path[1].ct_id for v in performer} == {ATTESTER}
    assert {v.path[2].ct_id for v in performer} == {PROFESSIONAL}


def test_the_attestation_reads_reason_committer_committed_and_pending(parts):
    att = [v for v in parts.parts if v.roles[:1] == ("attestation",)]
    assert {v.path[0].ct_id for v in att} == {LEGAL_AUTHENTICATION}
    roles = {v.role for v in att}
    assert {"reason", "committed", "pending"} <= roles
    assert next(v for v in att if v.role == "reason").component.ct_id == REASON
    assert next(v for v in att if v.role == "pending").elements == {"false-value": "false"}
    committer = [v for v in att if v.roles[1:2] == ("committer",)]
    assert committer and {v.path[1].ct_id for v in committer} == {LEGAL_AUTHENTICATOR}


def test_the_workflow_cluster_is_read(parts):
    wf = [v for v in parts.parts if v.roles[:1] == ("workflow",)]
    assert wf and {v.path[0].ct_id for v in wf} == {WORKFLOW}
    assert any(v.elements.get("symbol") == "final" for v in wf)


def test_one_details_cluster_under_two_parties_keeps_them_apart(parts):
    """The Health Professional details cluster serves the Author, the Attester and the Legal Authenticator; each
    value's path and roles say which."""
    pro = [v for v in parts.parts if any(c.ct_id == PROFESSIONAL for c in v.path) and v.component.ct_id == GIVEN_NAME]
    owners = {tuple(c.ct_id for c in v.path[: v.path.index(next(c for c in v.path if c.ct_id == PROFESSIONAL))]) for v in pro}
    assert (AUTHOR,) in owners and (ATTESTER_PARTICIPATION, ATTESTER) in owners and (LEGAL_AUTHENTICATION, LEGAL_AUTHENTICATOR) in owners


def test_an_exceptional_value_in_the_subjects_details_is_read(lab):
    r = read_record(LAB_EV, lab, reference_model=True)
    ev = [v for v in r.parts if v.exceptional]
    assert len(ev) == 1 and ev[0].exceptional.code == "ASKR" and ev[0].exceptional.origin == "source"
    assert ev[0].roles[:2] == ("subject", "party-details") and ev[0].component.label == "Date of Birth"


def test_a_party_with_a_name_only_reads_its_name_on_a_component_made_for_the_element():
    """The Credit Note's subject and provider are named Parties with no details and no Party component of that
    label: the reader makes one for the element (its ct_id the element's name), and the Party's name for its own."""
    model = read_model(load_package(CREDIT, "jkuyr38hydqaiwlq5vhp2rjr"))
    r = read_record(CREDIT / "record.xml", model, reference_model=True)
    names = [v for v in r.parts if v.role == "party-name"]
    assert names and {v.path[0].ct_id for v in names} <= {"subject", "provider"} | set(model.components)
    assert all(v.component.ct_id == "party-name" and v.component.sdc_type == "XdString" for v in names)
    assert all(v.elements["xdstring-value"] for v in names)
    plain = read_record(CREDIT / "record.xml", model)
    assert len(plain.values) == len(r.values) - len(r.parts)


def test_the_slot_table_names_the_reference_model_elements():
    assert RM_SLOTS["Participation"] == {"performer": "Party", "function": "XdString", "mode": "XdString",
                                         "start": "dateTime", "end": "dateTime"}
    assert {"subject", "provider", "performer", "committer", "party-details", "workflow"} <= RM_PARTS
    assert {"start", "end", "party-name", "committed", "pending", "function", "reason"} <= RM_ELEMENTS
    assert not RM_PARTS & RM_ELEMENTS
    assert all(len(n) < 24 for n in RM_PARTS | RM_ELEMENTS)   # never a CUID2


# ------------------------------------------------------------------ the MCP surface

def test_the_mcp_tools_reach_the_parts():
    from sdcreader import mcp_server as srv
    d = srv._handle_describe_model({"directory": str(LAB)})
    rm = d["reference_model"]
    assert rm["data_cluster"] == DATA_CLUSTER and d["root"]["ct_id"] == DATA_CLUSTER
    assert rm["parts"][ATTESTER_PARTICIPATION]["elements"]["performer"]["ct_id"] == ATTESTER
    assert rm["parts"]["zptekdommw56yiz9lqjy5dga"]["sdc_type"] == "DM"
    assert rm["parts"]["zptekdommw56yiz9lqjy5dga"]["elements"]["subject"] == {"rm_type": "sdc4:PartyType"}
    assert {p["ct_id"] for p in rm["unplaced_parties"]} == {PATIENT, AUTHOR}

    leaves = srv._handle_list_leaves({"directory": str(LAB), "parts": True, "limit": 200})
    assert leaves["total"] == rm["part_leaves"] and leaves["leaves"][0]["roles"] == ["", "party-details", "", ""]
    plain = srv._handle_list_leaves({"directory": str(LAB)})
    assert "roles" not in plain["leaves"][0]

    r = srv._handle_read_record({"record": str(LAB_RECORD), "directory": str(LAB), "reference_model": True, "limit": 200})
    assert r["total"] == 126 and r["parts"] == 104
    start = next(v for v in r["values"] if v["role"] == "start")
    assert start["path_ct_ids"] == [ATTESTER_PARTICIPATION] and start["elements"] == {"xdtemporal-datetime": "2026-10-01T09:00:00+01:00"}
    before = srv._handle_read_record({"record": str(LAB_RECORD), "directory": str(LAB)})
    assert before["total"] == 22 and "parts" not in before and "roles" not in before["values"][0]
