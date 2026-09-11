"""artefact_schemas.validate_payload (spec T113b -- a real, confirmed bug found live while
building strategy_research's real handler): every payload reaching this function is already
JSON-shaped (model_dump(mode="json"), a request body, or a DB JSONB read), never a live object
with a real datetime/date instance -- strict-mode validation must accept that real
representation, never reject a schema's own genuinely-valid ISO date string.
"""

import pytest
from pydantic import ValidationError

from src.orchestration.artefact_schemas import UnknownArtefactTypeError, validate_payload


def test_a_json_iso_datetime_string_validates_against_a_strict_model_field():
    """Confirmed live: re-validating a real, already-produced ResearchDirective payload (its own
    `generated_at` a JSON ISO string, exactly what model_dump(mode="json") produces) raised
    "Input should be a valid datetime" before this fix -- strict=True rejected the JSON
    representation of the model's own real field."""
    payload = {
        "generated_at": "2026-09-11T14:10:09.319884Z",
        "market_regime": "Sideways",
        "risk_tolerance": "Low",
        "strategy_themes": [],
        "priority_sectors": [],
        "expected_outcomes": "test",
        "participating_agents": ["MarketAnalystAgent"],
        "is_fallback_directive": False,
    }
    normalised = validate_payload("ResearchDirective", payload)
    assert normalised["generated_at"] == "2026-09-11T14:10:09.319884Z"


def test_an_unexpected_field_is_still_rejected():
    """strict=False only relaxes type coercion, never which fields are allowed -- every model's
    own extra="forbid" must still catch a field that doesn't belong (a real hallucinated-field
    guard, unrelated to this fix)."""
    payload = {
        "generated_at": "2026-09-11T14:10:09.319884Z",
        "market_regime": "Sideways",
        "risk_tolerance": "Low",
        "strategy_themes": [],
        "priority_sectors": [],
        "expected_outcomes": "test",
        "participating_agents": [],
        "is_fallback_directive": False,
        "not_a_real_field": "should be rejected",
    }
    with pytest.raises(ValidationError):
        validate_payload("ResearchDirective", payload)


def test_a_missing_required_field_is_still_rejected():
    with pytest.raises(ValidationError):
        validate_payload("DeploymentRecommendation", {"recommended_status": "PaperTrading"})


def test_an_unregistered_artefact_type_raises():
    with pytest.raises(UnknownArtefactTypeError):
        validate_payload("NotARealArtefactType", {})
