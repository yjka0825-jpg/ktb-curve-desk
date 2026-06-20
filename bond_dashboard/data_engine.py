from __future__ import annotations

import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from .config import BUNDLED_BASELINE, INSTRUMENTS, NAVER_REUTERS_CODES, PREVIOUS_CLOSE, YAHOO_TICKERS

KST = ZoneInfo("Asia/Seoul")
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 45)


@dataclass(frozen=True)
class Observation:
    instrument_id: str
    value: float
    status: str
    source: str
    as_of: datetime


@dataclass(frozen=True)
class MarketSnapshot:
    observations: dict[str, Observation]
    previous_close: dict[str, float]
    futures_5m_change: float
    generated_at: datetime

    @property
    def values(self) -> dict[str, float]:
        return {key: item.value for key, item in self.observations.items()}


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


def _seed(*parts: object) -> int:
    text = "|".join(map(str, parts)).encode("utf-8")
    return int(hashlib.sha256(text).hexdigest()[:8], 16)


def _minute_factors(ts: datetime) -> tuple[float, float, float]:
    rng = np.random.default_rng(_seed(ts.date(), ts.hour, ts.minute))
    return tuple(rng.normal(0, scale) for scale in (0.0040, 0.0030, 0.0020))


def _mock_yield(instrument_id: str, baseline: float, ts: datetime) -> float:
    meta = INSTRUMENTS[instrument_id]
    tenor = float(meta["tenor"])
    level, slope, curve = _minute_factors(ts)
    slope_loading = (tenor - 10) / 27
    curve_loading = -((tenor - 16.5) / 16.5) ** 2 + 0.35
    idio = np.random.default_rng(_seed(instrument_id, ts.isoformat())).normal(0, 0.0012)
    return baseline + level + slope * slope_loading + curve * curve_loading + idio


def five_minute_mock_sma(instrument_id: str, baseline: float, ts: datetime) -> float:
    points = [_mock_yield(instrument_id, baseline, ts - timedelta(minutes=i)) for i in range(5)]
    return round(float(np.mean(points)), 4)


def _futures_path(day: date, minute_index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    count = max(minute_index + 1, 6)
    rng = np.random.default_rng(_seed("futures", day))
    shocks = rng.normal(0, 0.018, count)
    jumps = np.zeros(count)
    if count > 95:
        jumps[90] = (-1 if _seed(day, "direction") % 2 else 1) * 0.16
    ktbf10 = 111.35 + np.cumsum(shocks + jumps)
    ktbf3 = 104.72 + np.cumsum(shocks * 0.38)
    direction = -1 if _seed(day, "foreign") % 2 else 1
    foreign10 = np.cumsum(rng.normal(direction * 7.5, 42, count)).round().astype(int)
    foreign3 = np.cumsum(rng.normal(direction * 3.0, 28, count)).round().astype(int)
    return ktbf3, ktbf10, foreign3, foreign10


def _futures_observations(ts: datetime) -> tuple[dict[str, Observation], float]:
    start = datetime.combine(ts.date(), MARKET_OPEN, KST)
    minute_index = max(0, int((ts - start).total_seconds() // 60))
    ktbf3, ktbf10, foreign3, foreign10 = _futures_path(ts.date(), minute_index)
    index = min(minute_index, len(ktbf10) - 1)
    prior_index = max(0, index - 5)
    change = round(float(ktbf10[index] - ktbf10[prior_index]), 3)
    values = {
        "KTBF3_PRICE": float(ktbf3[index]),
        "KTBF10_PRICE": float(ktbf10[index]),
        "KTBF3_FOREIGN_NET": int(foreign3[index]),
        "KTBF10_FOREIGN_NET": int(foreign10[index]),
    }
    observations = {
        key: Observation(key, value, "MOCK", "KOFIA 기준 모킹", ts)
        for key, value in values.items()
    }
    return observations, change


def _fetch_yahoo_ticker(
    instrument_id: str,
    ticker: str,
    now: datetime,
    getter: Callable = requests.get,
) -> Observation | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    try:
        response = getter(
            url, params={"range": "2d", "interval": "1m"}, timeout=3,
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
        return Observation(instrument_id, round(value, 4), status, f"Yahoo {ticker}", stamp)
    except Exception:
        return None


def fetch_yahoo_yields(now: datetime | None = None) -> dict[str, Observation]:
    """Best-effort Yahoo adapter; unsupported/rate-limited tickers simply return no row."""
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
    """Read the public Naver Pay Securities/Refinitiv intraday bond chart."""
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


def fetch_kofia_baseline(timeout: float = 5.0) -> dict[str, float]:
    """Best-effort parser for public KOFIA tables; failure is an expected fallback path."""
    url = "https://www.kofiabond.or.kr/html/MAIN.html"
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    tables = pd.read_html(io.StringIO(response.text))
    result: dict[str, float] = {}
    aliases = {
        "국고채권3년": "KTB_3Y", "국고채권5년": "KTB_5Y", "국고채권10년": "KTB_10Y",
        "국고채권20년": "KTB_20Y", "국고채권30년": "KTB_30Y",
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
    kofia: dict[str, float] | None = None,
    admin_override: dict[str, float] | None = None,
) -> MarketSnapshot:
    now = (now or datetime.now(KST)).astimezone(KST)
    market_ts = effective_market_time(now)
    baseline = dict(BUNDLED_BASELINE)
    source = {key: ("MOCK", "내장 데모 기준값") for key in baseline}
    if kofia:
        for key, value in kofia.items():
            if key in baseline:
                baseline[key] = value
                source[key] = ("MOCK", "KOFIA 종가 기반 모킹")
    if admin_override:
        for key, value in admin_override.items():
            if key in baseline:
                baseline[key] = value
                source[key] = ("MOCK", "관리자 종가 기반 모킹")
    observations: dict[str, Observation] = {}
    for key, base_value in baseline.items():
        status, label = source[key]
        observations[key] = Observation(
            key, five_minute_mock_sma(key, base_value, market_ts), status, label, market_ts
        )
    for key, observation in (naver or {}).items():
        if key in observations:
            observations[key] = observation
    for key, observation in (yahoo or {}).items():
        if key in observations:
            observations[key] = observation
    futures, change = _futures_observations(market_ts)
    observations.update(futures)
    previous = dict(PREVIOUS_CLOSE)
    for key, value in (naver_previous or {}).items():
        if key in previous:
            previous[key] = value
    for key in previous:
        if kofia and key in kofia:
            previous[key] = kofia[key]
        if admin_override and key in admin_override:
            previous[key] = admin_override[key]
    return MarketSnapshot(observations, previous, change, now)


def safe_provider(provider: Callable[[], dict], default: dict | None = None) -> dict:
    try:
        return provider()
    except Exception:
        return default or {}
