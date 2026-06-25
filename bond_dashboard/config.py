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
    "KTBF3_PRICE": {"label": "3년 국채선물", "unit": "pt", "kind": "future", "tenor": 3},
    "KTBF10_PRICE": {"label": "10년 국채선물", "unit": "pt", "kind": "future", "tenor": 10},
    "KTBF10_FOREIGN_NET": {"label": "10년 선물 외국인 누적", "unit": "계약", "kind": "flow", "tenor": 10},
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

ECOS_STAT_CODE = "817Y002"
ECOS_KTB_ITEM_CODES = {
    "KTB_3Y": "010200000",
    "KTB_5Y": "010200001",
    "KTB_10Y": "010210000",
    "KTB_20Y": "010220000",
    "KTB_30Y": "010230000",
}

STATUS_LABELS = {
    "LIVE": "LIVE",
    "DELAYED": "지연/공식일별",
    "CSV": "관리자 CSV",
    "EMPTY": "실데이터 없음",
}
