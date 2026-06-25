from bond_dashboard.analytics import calculate_spreads, evaluate_alerts, newly_triggered, traffic_light


def sample_values():
    return {
        "KTB_3Y": 3.00,
        "KTB_5Y": 3.05,
        "KTB_10Y": 3.10,
        "KTB_20Y": 3.08,
        "KTB_30Y": 3.10,
        "CORP_AA0_5Y": 3.45,
        "CORP_AA0_10Y": 3.60,
        "SPECIAL_AAA_10Y": 3.30,
        "SPECIAL_AAA_20Y": 3.31,
        "SPECIAL_AAA_30Y": 3.32,
        "KTBF3_PRICE": 104.0,
        "KTBF10_PRICE": 111.0,
    }


def test_spread_formulas_and_boundary_alerts():
    spreads = calculate_spreads(sample_values())
    assert spreads["30Y-3Y"] == 10.0
    assert spreads["30Y-10Y"] == 0.0
    assert spreads["20Y-30Y"] == -2.0
    assert spreads["AA0 5Y-국고 5Y"] == 40.0
    alerts = evaluate_alerts(spreads, -0.15, 0)
    ids = {alert.alert_id for alert in alerts}
    assert {"term_premium", "ultra_long", "futures_crash"} <= ids


def test_traffic_light_priority():
    assert traffic_light({"30Y-10Y": 1, "30Y-3Y": 11})[0] == "GREEN"
    assert traffic_light({"30Y-10Y": 1, "30Y-3Y": 10})[0] == "YELLOW"
    assert traffic_light({"30Y-10Y": 0, "30Y-3Y": 10})[0] == "RED"
    assert traffic_light({"30Y-10Y": None, "30Y-3Y": None})[0] == "GRAY"


def test_alert_only_retriggers_after_normalization():
    spreads = calculate_spreads(sample_values())
    active = evaluate_alerts(spreads, 0, 0)
    first, state = newly_triggered(set(), active)
    second, _ = newly_triggered(state, active)
    assert first
    assert second == []
    _, cleared = newly_triggered(state, [])
    third, _ = newly_triggered(cleared, active)
    assert third


def test_futures_foreign_thresholds():
    spreads = {"30Y-3Y": 20, "30Y-10Y": 5, "20Y-30Y": -1}
    assert {a.alert_id for a in evaluate_alerts(spreads, 0, -3000)} == {"futures_crash"}
    assert {a.alert_id for a in evaluate_alerts(spreads, 0, 3000)} == {"futures_surge"}


def test_missing_values_are_not_alerted():
    spreads = calculate_spreads({"KTB_3Y": 3.0})
    assert spreads["30Y-3Y"] is None
    assert traffic_light(spreads)[0] == "GRAY"
    assert evaluate_alerts(spreads, None, None) == []
