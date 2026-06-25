"""Build the public GitHub Pages snapshot without fabricating market values."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ECOS_STAT_CODE = "817Y002"
ECOS_CODES = {
    "KTB_3Y": "010200000",
    "KTB_5Y": "010200001",
    "KTB_10Y": "010210000",
    "KTB_20Y": "010220000",
    "KTB_30Y": "010230000",
}
NAVER_CODES = {
    "KTB_3Y": "KR3YT=RR",
    "KTB_5Y": "KR5YT=RR",
    "KTB_10Y": "KR10YT=RR",
    "KTB_20Y": "KR20YT=RR",
    "KTB_30Y": "KR30YT=RR",
}


def is_market_open(now: datetime) -> bool:
    return now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (15, 45)


def fetch_ecos_one(item: tuple[str, str], now: datetime, api_key: str) -> tuple[str, dict] | None:
    instrument_id, item_code = item
    start = (now - timedelta(days=14)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    url = (
        "https://ecos.bok.or.kr/api/StatisticSearch/"
        f"{api_key}/json/kr/1/10/{ECOS_STAT_CODE}/D/{start}/{end}/{item_code}"
    )
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.load(response)
        rows = payload.get("StatisticSearch", {}).get("row") or []
        rows = [row for row in rows if row.get("DATA_VALUE") not in (None, "")]
        if not rows:
            return None
        latest = max(rows, key=lambda row: row["TIME"])
        stamp = datetime.strptime(latest["TIME"], "%Y%m%d").replace(hour=16, tzinfo=KST)
        return instrument_id, {
            "value": round(float(latest["DATA_VALUE"]), 4),
            "status": "DELAYED",
            "source": f"한국은행 ECOS {ECOS_STAT_CODE} {latest.get('ITEM_NAME1', item_code)}",
            "as_of": stamp.isoformat(),
        }
    except Exception:
        return None


def fetch_naver_one(item: tuple[str, str], now: datetime) -> tuple[str, dict, float] | None:
    instrument_id, code = item
    query = urllib.parse.urlencode({
        "reutersCode": code,
        "category": "bond",
        "chartInfoType": "governmentBond",
        "scriptChartType": "day",
    })
    request = urllib.request.Request(
        f"https://m.stock.naver.com/front-api/chart/pricesByPeriod?{query}",
        headers={"User-Agent": "Mozilla/5.0", "Referer": f"https://m.stock.naver.com/marketindex/bond/{code}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.load(response)
        result = payload["result"]
        points = [
            (datetime.strptime(row["localDateTime"], "%Y%m%d%H%M%S").replace(tzinfo=KST), float(row["currentPrice"]))
            for row in result.get("priceInfos", [])
        ]
        if not points:
            return None
        latest = max(stamp for stamp, _ in points)
        window = [value for stamp, value in points if latest - timedelta(minutes=5) <= stamp <= latest]
        status = "LIVE" if is_market_open(now) and now - latest <= timedelta(minutes=10) else "DELAYED"
        return instrument_id, {
            "value": round(sum(window) / len(window), 4),
            "status": status,
            "source": f"Naver Pay·Refinitiv {code}",
            "as_of": latest.isoformat(),
        }, float(result["lastClosePrice"])
    except Exception:
        return None


def main() -> None:
    now = datetime.now(KST).replace(second=0, microsecond=0)
    api_key = os.getenv("BOK_API_KEY") or os.getenv("ECOS_API_KEY") or "sample"
    observations: dict[str, dict] = {}
    previous: dict[str, float] = {}

    with ThreadPoolExecutor(max_workers=5) as pool:
        ecos_rows = list(pool.map(lambda item: fetch_ecos_one(item, now, api_key), ECOS_CODES.items()))
    for row in ecos_rows:
        if row:
            instrument_id, observation = row
            observations[instrument_id] = observation
            previous[instrument_id] = observation["value"]

    with ThreadPoolExecutor(max_workers=5) as pool:
        naver_rows = list(pool.map(lambda item: fetch_naver_one(item, now), NAVER_CODES.items()))
    for row in naver_rows:
        if row:
            instrument_id, observation, prior = row
            observations[instrument_id] = observation
            previous[instrument_id] = prior

    payload = {
        "generated_at": now.isoformat(),
        "market_open": is_market_open(now),
        "observations": observations,
        "previous_close": previous,
        "notice": "실데이터가 없는 항목은 비워 둡니다. 모킹 데이터는 생성하지 않습니다.",
    }
    output = Path(__file__).resolve().parents[1] / "docs" / "data" / "latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
