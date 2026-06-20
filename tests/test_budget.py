import pytest

from bond_dashboard.budget import apply_execution


def test_budget_accumulates():
    result = apply_execution(100, 35, 25)
    assert result.spent == 60
    assert result.remaining == 40


@pytest.mark.parametrize("limit,spent,execution", [(100, 80, 21), (-1, 0, 0), (100, -1, 1)])
def test_budget_rejects_invalid(limit, spent, execution):
    with pytest.raises(ValueError):
        apply_execution(limit, spent, execution)
