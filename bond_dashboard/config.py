from __future__ import annotations

TENORS = [3, 5, 10, 20, 30]

INSTRUMENTS = {
    "KTB_3Y": {"label": "국고채 3Y", "unit": "%", "kind": "yield", "tenor": 3},
    "KTB_5Y": {"label": "국고채 5Y", "unit": "%", "kind": "yield", "tenor": 5},
    "KTB_10Y": {"label": "국고채 10Y", "unit": "%", "kind": "yield", "tenor": 10},
    "KTB_20Y": {"label": "국고채 20Y", "unit": "%", "kind": "yield", "tenor": 20},
    "KTB_30Y": {"label": "국고채 30Y", "unit": "%", "kind": "yield", "tenor": 30},
    "CORP_AA0_5Y": {"label": "무보증 AA0 5Y", "unit": "%", "kind": "yield", "tenor": 5},
    "CORP_AA0_10Y": {"label": "무보증 AA0 10Y", "unit": "%", "kind": "yield", "tenor": 10},
    "SPECIAL_AAA_10Y": {"label": "특수채 AAA 10Y", "unit": "%", "kind": "yield", "tenor": 10},
    "SPECIAL_AAA_20Y": {"label": "특수채 AAA 20Y", "unit": "%", "kind": "yield", "tenor": 20},
    "SPECIAL_AAA_30Y": {"label": "특수채 AAA 30Y", "unit": "%", "kind": "yield", "tenor": 30},
}

YAHOO_TICKERS = {
    "KTB_3Y": "KR3Y.F",
    "KTB_5Y": "KR5Y.F",
    "KTB_10Y": "KR10Y.F",
    "KTB_20Y": "KR20Y.F",
    "KTB_30Y": "KR30Y.F",
}

NAVER_REUTERS_CODES = {
    "KTB_3Y": "KR3YT=RR",
    "KTB_5Y": "KR5YT=RR",
    "KTB_10Y": "KR10YT=RR",
    "KTB_20Y": "KR20YT=RR",
    "KTB_30Y": "KR30YT=RR",
}

# This is deliberately a demo anchor, not represented as an observed market close.
BUNDLED_BASELINE = {
    "KTB_3Y": 3.180,
    "KTB_5Y": 3.205,
    "KTB_10Y": 3.235,
    "KTB_20Y": 3.185,
    "KTB_30Y": 3.170,
    "CORP_AA0_5Y": 3.645,
    "CORP_AA0_10Y": 3.755,
    "SPECIAL_AAA_10Y": 3.455,
    "SPECIAL_AAA_20Y": 3.425,
    "SPECIAL_AAA_30Y": 3.415,
}

PREVIOUS_CLOSE = {
    "KTB_3Y": 3.165,
    "KTB_5Y": 3.195,
    "KTB_10Y": 3.225,
    "KTB_20Y": 3.180,
    "KTB_30Y": 3.175,
}

STATUS_LABELS = {
    "LIVE": "LIVE",
    "DELAYED": "지연",
    "MOCK": "MOCK",
}
