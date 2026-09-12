from iaso_lite.patient import compact_patient_view
from iaso_lite.synthesis import _patient_brief

PATIENT = {
    "patient_id": "p1",
    "ptsd": {"still_active": True, "age_at_onset": 40},
    "treatment": {"medications": [{"drug": "Sertraline 100 MG Oral Tablet", "start": "2020-01-01"}]},
    "pat_screening": {
        "pcl5_total_score": 48,
        "caps5_severity": "Severe",
        "trauma_profile": {"index_trauma_type": "Military sexual trauma (MST)"},
        "treatment_history": {
            "prior_trauma_focused_therapy": {
                "attempted": True,
                "type": "Prolonged Exposure",
                "outcome": "Non-responder",
            }
        },
        "contraindications": {"current_maoi_use": True, "pregnancy_possible": False},
    },
}


def test_pat_screening_survives_compaction_and_reaches_the_brief():
    pc = compact_patient_view(PATIENT)
    assert pc["pat_screening"]["pcl5_total_score"] == 48
    assert pc["pat_screening"]["caps5_severity"] == "Severe"
    assert pc["pat_screening"]["prior_trauma_focused_therapy"] == {
        "type": "Prolonged Exposure",
        "outcome": "Non-responder",
    }
    assert pc["pat_screening"]["flagged_contraindications"] == ["current_maoi_use"]

    brief = _patient_brief(pc)
    assert "PCL-5=48" in brief
    assert "CAPS-5 severity=Severe" in brief
    assert "Military sexual trauma" in brief
    assert "Non-responder" in brief
    assert "current_maoi_use" in brief


def test_missing_pat_screening_is_silently_absent_not_an_error():
    pc = compact_patient_view({"patient_id": "p2", "ptsd": {}, "treatment": {}})
    assert pc["pat_screening"] is None
    brief = _patient_brief(pc)
    assert "PCL-5" not in brief
