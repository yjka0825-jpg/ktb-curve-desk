from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetResult:
    limit: float
    spent: float
    remaining: float


def apply_execution(limit: float, spent: float, execution: float) -> BudgetResult:
    values = (limit, spent, execution)
    if any(value < 0 for value in values):
        raise ValueError("금액은 0 이상이어야 합니다.")
    if spent > limit:
        raise ValueError("누적 집행액이 월 한도를 초과했습니다.")
    if spent + execution > limit:
        raise ValueError("이번 집행액이 월 잔여 한도를 초과합니다.")
    new_spent = round(spent + execution, 4)
    return BudgetResult(limit=limit, spent=new_spent, remaining=round(limit - new_spent, 4))
