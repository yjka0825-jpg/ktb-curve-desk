from __future__ import annotations

import io
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from .config import (
    ECOS_KTB_ITEM_CODES,
    ECOS_STAT_CODE,
    INSTRUMENTS,
    NAVER_REUTERS_CODES,
    YAHOO_TICKERS,
)

KST = ZoneInfo("Asia/Seoul")
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 45)


@dataclass(frozen=True)
class Observation:
    instrument_id: str
    value: float | None
    status: str
    source: str
    as_of: datetime | None


@dataclass(frozen=True)
class MarketSnapshot:
    observations: dict[str, Observation]
    previous_close: dict[str, float]
    futures_5m_change: float | None
    generated_at: datetime

    @property
    def values(self) -> dict[str, float]:
        return {
            key: item.value
            for key, item in self.observations.items()
            if item.value is not None
        }


def _is_holiday(day: date) -> bool:
    try:
        import holidays

        return day in holidays.country_holidays("KR", years=[day.year])
    except Exception:
        return False


def _is_business_day(day: date) -> bool:
    return day.weekday() < 5 and not _is_holiday(day)


def previous_business_day(day: date) -> date:
    candidate = day - timedelta(days=1)
    while not _is_business_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def effective_market_time(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(KST)).astimezone(KST)
    if not _is_business_day(now.date()):
        day = previous_business_day(now.date())
        return datetime.combine(day, MARKET_CLOSE, KST)
    if now.time() < MARKET_OPEN:
        day = previous_business_day(now.date())
        return datetime.combine(day, MARKET_CLOSE, KST)
    if now.time() > MARKET_CLOSE:
        return datetime.combine(now.date(), MARKET_CLOSE, KST)
    return now.replace(second=0, microsecond=0)


def market_is_open(now: datetime | None = None) -> bool:
    now = (now or datetime.now(KST)).astimezone(KST)
    return _is_business_day(now.date()) and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def _fetch_yahoo_ticker(
    instrument_id: str,
    ticker: str,
    now: datetime,
    getter: Callable = requests.get,
) -> Observation | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    try:
        response = getter(
            url,
            params={"range": "2d", "interval": "1m"},
            timeout=3,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
        timestamps = result.get("timestamp") or []
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close") or []
        points = [(stamp, value) for stamp, value in zip(timestamps, closes) if value is not None]
        if not points:
            return None
        tail = points[-5:]
        value = float(np.mean([point[1] for point in tail]))
        stamp = datetime.fromtimestamp(tail[-1][0], tz=KST)
        status = "LIVE" if now - stamp <= timedelta(minutes=10) else "DELAYED"
        return Observation(instrument_id, round(value, 4), status, f"Yahoo Finance {ticker}", stamp)
    except Exception:
        return None


def fetch_yahoo_yields(now: datetime | None = None) -> dict[str, Observation]:
    now = (now or datetime.now(KST)).astimezone(KST)
    with ThreadPoolExecutor(max_workers=len(YAHOO_TICKERS)) as pool:
        jobs = [pool.submit(_fetch_yahoo_ticker, key, ticker, now) for key, ticker in YAHOO_TICKERS.items()]
    observations = [job.result() for job in jobs]
    return {item.instrument_id: item for item in observations if item is not None}


def _fetch_naver_ticker(
    instrument_id: str,
    reuters_code: str,
    now: datetime,
    getter: Callable = requests.get,
) -> tuple[Observation, float] | None:
    url = "https://m.stock.naver.com/front-api/chart/pricesByPeriod"
    try:
        response = getter(
            url,
            params={
                "reutersCode": reuters_code,
                "category": "bond",
                "chartInfoType": "governmentBond",
                "scriptChartType": "day",
            },
            timeout=4,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": f"https://m.stock.naver.com/marketindex/bond/{reuters_code}",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("isSuccess"):
            return None
        result = payload.get("result") or {}
        points: list[tuple[datetime, float]] = []
        for row in result.get("priceInfos") or []:
            stamp = datetime.strptime(row["localDateTime"], "%Y%m%d%H%M%S").replace(tzinfo=KST)
            points.append((stamp, float(row["currentPrice"])))
        if not points:
            return None
        latest = max(stamp for stamp, _ in points)
        window_start = latest - timedelta(minutes=5)
        window_values = [value for stamp, value in points if window_start <= stamp <= latest]
        if not window_values:
            return None
        status = "LIVE" if market_is_open(now) and now - latest <= timedelta(minutes=10) else "DELAYED"
        observation = Observation(
            instrument_id=instrument_id,
            value=round(float(np.mean(window_values)), 4),
            status=status,
            source=f"Naver Pay·Refinitiv {reuters_code}",
            as_of=latest,
        )
        previous_close = float(result["lastClosePrice"])
        return observation, previous_close
    except Exception:
        return None


def fetch_naver_yields(now: datetime | None = None) -> tuple[dict[str, Observation], dict[str, float]]:
    now = (now or datetime.now(KST)).astimezone(KST)
    with ThreadPoolExecutor(max_workers=len(NAVER_REUTERS_CODES)) as pool:
        jobs = [
            pool.submit(_fetch_naver_ticker, key, code, now)
            for key, code in NAVER_REUTERS_CODES.items()
        ]
    rows = [job.result() for job in jobs]
    valid = [row for row in rows if row is not None]
    observations = {row[0].instrument_id: row[0] for row in valid}
    previous = {row[0].instrument_id: row[1] for row in valid}
    return observations, previous


def _fetch_ecos_item(
    instrument_id: str,
    item_code: str,
    api_key: str,
    now: datetime,
    getter: Callable = requests.get,
) -> Observation | None:
    end = now.strftime("%Y%m%d")
    start = (now - timedelta(days=14)).strftime("%Y%m%d")
    url = (
        "https://ecos.bok.or.kr/api/StatisticSearch/"
        f"{api_key}/json/kr/1/10/{ECOS_STAT_CODE}/D/{start}/{end}/{item_code}"
    )
    try:
        response = getter(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("StatisticSearch", {}).get("row") or []
        usable = [row for row in rows if row.get("DATA_VALUE") not in (None, "")]
        if not usable:
            return None
        latest = max(usable, key=lambda row: row["TIME"])
        as_of = datetime.strptime(latest["TIME"], "%Y%m%d").replace(hour=16, tzinfo=KST)
        return Observation(
            instrument_id=instrument_id,
            value=round(float(latest["DATA_VALUE"]), 4),
            status="DELAYED",
            source=f"한국은행 ECOS {ECOS_STAT_CODE} {latest.get('ITEM_NAME1', item_code)}",
            as_of=as_of,
        )
    except Exception:
        return None


def fetch_ecos_yields(
    api_key: str | None = None,
    now: datetime | None = None,
) -> dict[str, Observation]:
    """Fetch official daily KTB yields from Bank of Korea ECOS.

    ECOS is an official daily data source, not a tick-by-tick intraday feed. If no
    key is supplied, the public "sample" key is used with its 10-row limit.
    """
    now = (now or datetime.now(KST)).astimezone(KST)
    key = api_key or os.getenv("BOK_API_KEY") or os.getenv("ECOS_API_KEY") or "sample"
    with ThreadPoolExecutor(max_workers=len(ECOS_KTB_ITEM_CODES)) as pool:
        jobs = [
            pool.submit(_fetch_ecos_item, instrument_id, item_code, key, now)
            for instrument_id, item_code in ECOS_KTB_ITEM_CODES.items()
        ]
    observations = [job.result() for job in jobs]
    return {item.instrument_id: item for item in observations if item is not None}


def fetch_kofia_baseline(timeout: float = 5.0) -> dict[str, float]:
    """Best-effort public KOFIA parser. It never fabricates missing values."""
    url = "https://www.kofiabond.or.kr/html/MAIN.html"
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    tables = pd.read_html(io.StringIO(response.text))
    result: dict[str, float] = {}
    aliases = {
        "국고채권3년": "KTB_3Y",
        "국고채권5년": "KTB_5Y",
        "국고채권10년": "KTB_10Y",
        "국고채권20년": "KTB_20Y",
        "국고채권30년": "KTB_30Y",
    }
    for table in tables:
        for _, row in table.astype(str).iterrows():
            joined = "".join(row.tolist()).replace(" ", "")
            for label, instrument_id in aliases.items():
                if label not in joined:
                    continue
                numbers = pd.to_numeric(row, errors="coerce").dropna()
                if not numbers.empty:
                    result[instrument_id] = float(numbers.iloc[-1])
    return result


def parse_admin_csv(content: bytes | str) -> dict[str, float]:
    raw = io.BytesIO(content) if isinstance(content, bytes) else io.StringIO(content)
    frame = pd.read_csv(raw)
    required = {"as_of_kst", "instrument_id", "value", "unit", "quote_type"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"필수 CSV 열 누락: {', '.join(sorted(missing))}")
    allowed_ids = set(INSTRUMENTS)
    unknown = set(frame["instrument_id"].astype(str)) - allowed_ids
    if unknown:
        raise ValueError(f"알 수 없는 instrument_id: {', '.join(sorted(unknown))}")
    values = pd.to_numeric(frame["value"], errors="coerce")
    if values.isna().any() or (values <= 0).any():
        raise ValueError("value는 0보다 큰 숫자여야 합니다.")
    return dict(zip(frame["instrument_id"].astype(str), values.astype(float)))


def build_snapshot(
    now: datetime | None = None,
    yahoo: dict[str, Observation] | None = None,
    naver: dict[str, Observation] | None = None,
    naver_previous: dict[str, float] | None = None,
    ecos: dict[str, Observation] | None = None,
    kofia: dict[str, float] | None = None,
    admin_override: dict[str, float] | None = None,
) -> MarketSnapshot:
    now = (now or datetime.now(KST)).astimezone(KST)
    market_ts = effective_market_time(now)
    observations: dict[str, Observation] = {}

    for key, observation in (ecos or {}).items():
        if key in INSTRUMENTS:
            observations[key] = observation

    for key, value in (kofia or {}).items():
        if key in INSTRUMENTS:
            observations[key] = Observation(key, value, "DELAYED", "금융투자협회 공시", market_ts)

    for key, value in (admin_override or {}).items():
        if key in INSTRUMENTS:
            observations[key] = Observation(key, value, "CSV", "관리자 CSV", market_ts)

    for key, observation in (naver or {}).items():
        if key in INSTRUMENTS:
            observations[key] = observation

    for key, observation in (yahoo or {}).items():
        if key in INSTRUMENTS:
            observations[key] = observation

    previous: dict[str, float] = {}
    for key, observation in observations.items():
        if key.startswith("KTB_") and observation.value is not None:
            previous[key] = observation.value
    for key, value in (naver_previous or {}).items():
        if key in INSTRUMENTS:
            previous[key] = value

    return MarketSnapshot(observations, previous, None, now)


def safe_provider(provider: Callable, default=None):
    try:
        return provider()
    except Exception:
        return default if default is not None else {}
