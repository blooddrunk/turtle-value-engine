import pytest

from turtle_value_engine.calculations import FactBook, FactLookupError
from turtle_value_engine.models import Fact


def _fact(identifier: str, value: float | None) -> Fact:
    return Fact(
        id=identifier,
        field="hard_cash",
        value=value,
        period="AS_OF_2026-09-08",
        source_evidence_ids=["evidence-1"],
        confidence=1,
    )


def test_fact_book_rejects_ambiguous_field_period_duplicates():
    with pytest.raises(FactLookupError, match="duplicate normalized fact"):
        FactBook([_fact("fact-1", 100), _fact("fact-2", 90)])


def test_fact_book_preserves_null_and_lineage():
    book = FactBook([_fact("fact-1", None)])

    assert book.value("hard_cash", "AS_OF_2026-09-08") is None
    assert book.evidence_ids(["hard_cash"], "AS_OF_2026-09-08") == ["evidence-1"]
