from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bond_dashboard.data_engine import (
    _fetch_ecos_item, _fetch_naver_ticker, _fetch_yahoo_ticker, build_snapshot, effective_market_time, parse_admin_csv,
)

KST = ZoneInfo("Asia/Seoul")


def test_weekend_freezes_at_previous_close():
    saturday = datetime(2026, 6, 20, 12, 0, tzinfo=KST)
    effective = effective_market_time(saturday)
    assert effective.weekday() < 5
    assert (effective.hour, effective.minute) == (15, 45)
    one = build_snapshot(saturday)
    two = build_snapshot(datetime(2026, 6, 20, 22, 0, tzinfo=KST))
    assert one.values == two.values


def test_empty_snapshot_does_not_fabricate_values():
    ts = datetime(2026, 6, 22, 10, 0, tzinfo=KST)
    snapshot = build_snapshot(ts)
    assert snapshot.values == {}
    assert snapshot.observations == {}


def test_admin_override_is_csv_real_input():
    ts = datetime(2026, 6, 22, 10, 0, tzinfo=KST)
    changed = build_snapshot(ts, admin_override={"KTB_3Y": 4.0})
    assert changed.values["KTB_3Y"] == 4.0
    assert changed.observations["KTB_3Y"].status == "CSV"


def test_csv_validation():
    valid = "as_of_kst,instrument_id,value,unit,quote_type\n2026-06-20,KTB_3Y,3.2,percent,final_yield\n"
    assert parse_admin_csv(valid) == {"KTB_3Y": 3.2}
    with pytest.raises(ValueError):
        parse_admin_csv("instrument_id,value\nKTB_3Y,3.2\n")
    with pytest.raises(ValueError):
        parse_admin_csv("as_of_kst,instrument_id,value,unit,quote_type\nx,UNKNOWN,3.2,p,x\n")


def test_yahoo_payload_is_five_point_sma():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"chart": {"result": [{
                "timestamp": [1781917200, 1781917260, 1781917320, 1781917380, 1781917440],
                "indicators": {"quote": [{"close": [3.0, 3.1, 3.2, 3.3, 3.4]}]},
            }]}}

    now = datetime.fromtimestamp(1781917440, tz=KST)
    observation = _fetch_yahoo_ticker("KTB_3Y", "KR3Y.F", now, getter=lambda *a, **k: Response())
    assert observation is not None
    assert observation.value == 3.2
    assert observation.status == "LIVE"


def test_naver_payload_uses_five_minute_time_window():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"isSuccess": True, "result": {
                "lastClosePrice": 3.0,
                "priceInfos": [
                    {"localDateTime": "20260622100000", "currentPrice": 3.10},
                    {"localDateTime": "20260622100400", "currentPrice": 3.20},
                    {"localDateTime": "20260622100900", "currentPrice": 3.30},
                    {"localDateTime": "20260622101000", "currentPrice": 3.40},
                ],
            }}

    now = datetime(2026, 6, 22, 10, 10, tzinfo=KST)
    row = _fetch_naver_ticker("KTB_10Y", "KR10YT=RR", now, getter=lambda *a, **k: Response())
    assert row is not None
    observation, previous = row
    assert observation.value == 3.35
    assert observation.status == "LIVE"
    assert previous == 3.0


def test_ecos_payload_uses_latest_official_daily_value():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"StatisticSearch": {"row": [
                {"TIME": "20260621", "DATA_VALUE": "3.70", "ITEM_NAME1": "국고채(3년)"},
                {"TIME": "20260624", "DATA_VALUE": "3.81", "ITEM_NAME1": "국고채(3년)"},
            ]}}

    now = datetime(2026, 6, 25, 10, 0, tzinfo=KST)
    observation = _fetch_ecos_item("KTB_3Y", "010200000", "sample", now, getter=lambda *a, **k: Response())
    assert observation is not None
    assert observation.value == 3.81
    assert observation.status == "DELAYED"
    assert "한국은행 ECOS" in observation.source


def test_yahoo_overrides_naver_and_naver_supplies_previous_close():
    ts = datetime(2026, 6, 22, 10, 0, tzinfo=KST)
    from bond_dashboard.data_engine import Observation
    naver = {"KTB_3Y": Observation("KTB_3Y", 3.5, "LIVE", "Naver", ts)}
    yahoo = {"KTB_3Y": Observation("KTB_3Y", 3.6, "LIVE", "Yahoo", ts)}
    snapshot = build_snapshot(ts, yahoo=yahoo, naver=naver, naver_previous={"KTB_3Y": 3.4})
    assert snapshot.values["KTB_3Y"] == 3.6
    assert snapshot.previous_close["KTB_3Y"] == 3.4
