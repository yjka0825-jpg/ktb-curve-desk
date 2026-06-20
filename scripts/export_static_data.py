"""Build the public GitHub Pages snapshot using only the Python standard library."""

from __future__ import annotations

import hashlib
import json
import math
import random
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
CODES = {
    "KTB_3Y": "KR3YT=RR", "KTB_5Y": "KR5YT=RR", "KTB_10Y": "KR10YT=RR",
    "KTB_20Y": "KR20YT=RR", "KTB_30Y": "KR30YT=RR",
}
BASELINE = {"KTB_3Y": 3.18, "KTB_5Y": 3.205, "KTB_10Y": 3.235, "KTB_20Y": 3.185, "KTB_30Y": 3.17}
PREVIOUS = {"KTB_3Y": 3.165, "KTB_5Y": 3.195, "KTB_10Y": 3.225, "KTB_20Y": 3.18, "KTB_30Y": 3.175}


def is_market_open(now: datetime) -> bool:
    return now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (15, 45)


def fetch_one(item: tuple[str, str], now: datetime) -> tuple[str, dict, float] | None:
    instrument_id, code = item
    query = urllib.parse.urlencode({
        "reutersCode": code, "category": "bond", "chartInfoType": "governmentBond", "scriptChartType": "day",
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
        observation = {
            "value": round(sum(window) / len(window), 4), "status": status,
            "source": f"Naver Pay·Refinitiv {code}", "as_of": latest.isoformat(),
        }
        return instrument_id, observation, float(result["lastClosePrice"])
    except Exception:
        return None


def deterministic_market(now: datetime, ktb10: float) -> dict[str, dict]:
    key = f"{now:%Y-%m-%d-%H-%M}"
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    minute = max(0, min(405, (now.hour * 60 + now.minute) - 540))
    wave = math.sin(minute / 34) * 0.08
    ktbf10 = round(111.35 - (ktb10 - 3.2) * 1.7 + wave + rng.uniform(-0.018, 0.018), 3)
    ktbf3 = round(104.72 - wave * 0.3 + rng.uniform(-0.008, 0.008), 3)
    foreign = int(math.sin(minute / 70) * 2600 + (minute - 200) * 3 + rng.uniform(-180, 180))
    stamp = now.isoformat()
    return {
        "KTBF3_PRICE": {"value": ktbf3, "status": "MOCK", "source": "KOFIA 기준 모킹", "as_of": stamp},
        "KTBF10_PRICE": {"value": ktbf10, "status": "MOCK", "source": "KOFIA 기준 모킹", "as_of": stamp},
        "KTBF10_5M_CHANGE": {"value": round(rng.uniform(-0.11, 0.11), 3), "status": "MOCK", "source": "모킹", "as_of": stamp},
        "KTBF10_FOREIGN_NET": {"value": foreign, "status": "MOCK", "source": "장중 누적 모킹", "as_of": stamp},
    }


def main() -> None:
    now = datetime.now(KST).replace(second=0, microsecond=0)
    observations: dict[str, dict] = {}
    previous = dict(PREVIOUS)
    with ThreadPoolExecutor(max_workers=5) as pool:
        rows = list(pool.map(lambda item: fetch_one(item, now), CODES.items()))
    for instrument_id, baseline in BASELINE.items():
        observations[instrument_id] = {
            "value": baseline, "status": "MOCK", "source": "내장 데모 기준값", "as_of": now.isoformat(),
        }
    for row in rows:
        if row:
            instrument_id, observation, prior = row
            observations[instrument_id] = observation
            previous[instrument_id] = prior

    credit = {
        "CORP_AA0_5Y": (observations["KTB_5Y"]["value"] + 0.44, "무보증 AA0 5Y"),
        "CORP_AA0_10Y": (observations["KTB_10Y"]["value"] + 0.52, "무보증 AA0 10Y"),
        "SPECIAL_AAA_10Y": (observations["KTB_10Y"]["value"] + 0.22, "특수채 AAA 10Y"),
        "SPECIAL_AAA_20Y": (observations["KTB_20Y"]["value"] + 0.24, "특수채 AAA 20Y"),
        "SPECIAL_AAA_30Y": (observations["KTB_30Y"]["value"] + 0.25, "특수채 AAA 30Y"),
    }
    for instrument_id, (value, _) in credit.items():
        observations[instrument_id] = {
            "value": round(value, 4), "status": "MOCK", "source": "KOFIA 스프레드 기준 모킹", "as_of": now.isoformat(),
        }
    observations.update(deterministic_market(now, observations["KTB_10Y"]["value"]))
    payload = {
        "generated_at": now.isoformat(), "market_open": is_market_open(now),
        "observations": observations, "previous_close": previous,
    }
    output = Path(__file__).resolve().parents[1] / "docs" / "data" / "latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
