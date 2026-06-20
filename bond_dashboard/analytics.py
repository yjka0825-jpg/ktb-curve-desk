from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Alert:
    alert_id: str
    title: str
    guidance: str
    severity: str


def calculate_spreads(values: dict[str, float]) -> dict[str, float]:
    bp = lambda left, right: round((values[left] - values[right]) * 100, 2)
    return {
        "30Y-3Y": bp("KTB_30Y", "KTB_3Y"),
        "10Y-3Y": bp("KTB_10Y", "KTB_3Y"),
        "30Y-10Y": bp("KTB_30Y", "KTB_10Y"),
        "20Y-30Y": bp("KTB_20Y", "KTB_30Y"),
        "AA0 5Y-국고 5Y": bp("CORP_AA0_5Y", "KTB_5Y"),
        "AA0 10Y-국고 10Y": bp("CORP_AA0_10Y", "KTB_10Y"),
        "특수 AAA 10Y-국고 10Y": bp("SPECIAL_AAA_10Y", "KTB_10Y"),
        "특수 AAA 20Y-국고 20Y": bp("SPECIAL_AAA_20Y", "KTB_20Y"),
        "특수 AAA 30Y-국고 30Y": bp("SPECIAL_AAA_30Y", "KTB_30Y"),
        "선물 10Y-3Y": round(values["KTBF10_PRICE"] - values["KTBF3_PRICE"], 3),
    }


def traffic_light(spreads: dict[str, float]) -> tuple[str, str, str]:
    if spreads["30Y-10Y"] <= 0 or spreads["30Y-3Y"] <= 0:
        return "RED", "과열", "#ef4444"
    if spreads["30Y-3Y"] <= 10:
        return "YELLOW", "축소", "#f59e0b"
    return "GREEN", "적정", "#22c55e"


def evaluate_alerts(
    spreads: dict[str, float], futures_5m_change: float, foreign_10y_net: int
) -> list[Alert]:
    alerts: list[Alert] = []
    if spreads["30Y-3Y"] <= 10:
        alerts.append(Alert(
            "term_premium", "🚨 기간 프리미엄 축소 경보",
            "장기 보유 대가가 너무 적습니다. 30년물 신규 매수를 제한하고, 단기물(3Y/5Y) 또는 고금리 은행채(AAA)로 롤오버하며 관망을 권장합니다.",
            "danger",
        ))
    if spreads["30Y-10Y"] <= 0:
        alerts.append(Alert(
            "ultra_long", "💡 초장기 수급 왜곡 경보",
            "초장기물 과열 상태입니다. 부채 매칭용 30년물 추격 매수를 멈추고, 10년물이나 MBS 입찰 우회를 검토하세요.",
            "warning",
        ))
    if spreads["20Y-30Y"] >= 0:
        alerts.append(Alert(
            "belly_buy", "🟢 20Y 벨리 매수 시그널",
            "20년물 금리가 30년물을 역전하여 밸류에이션 매력이 극대화되었습니다. 듀레이션 갭 조절용 적극 매수 구간입니다.",
            "success",
        ))
    if futures_5m_change <= -0.15 or foreign_10y_net <= -3000:
        alerts.append(Alert(
            "futures_crash", "📉 국채선물 장중 폭락 경보",
            "외인 국채선물 대량 매도 및 가격 폭락으로 장중 금리 급등(상승) 추세가 강합니다. 현물 채권 매수 호가를 하향 조정(진입 금리를 더 높게 설정)하여 보수적으로 대응하세요.",
            "danger",
        ))
    if futures_5m_change >= 0.15 or foreign_10y_net >= 3000:
        alerts.append(Alert(
            "futures_surge", "📈 국채선물 장중 폭등 경보",
            "외인 대량 매수로 가격 폭등 및 장중 금리 급락 추세입니다. 당일 입찰(MBS 등) 낙찰을 원할 경우 비딩 금리를 당초 계획보다 0.5bp~1bp 낮춰 써내기를 권장합니다.",
            "info",
        ))
    return alerts


def newly_triggered(previous: set[str], current: list[Alert]) -> tuple[list[Alert], set[str]]:
    current_ids = {item.alert_id for item in current}
    return [item for item in current if item.alert_id not in previous], current_ids
