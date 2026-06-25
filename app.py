from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from streamlit_js_eval import streamlit_js_eval

from bond_dashboard.analytics import calculate_spreads, evaluate_alerts, newly_triggered, traffic_light
from bond_dashboard.budget import apply_execution
from bond_dashboard.config import INSTRUMENTS, STATUS_LABELS, TENORS
from bond_dashboard.data_engine import (
    KST,
    build_snapshot,
    fetch_ecos_yields,
    fetch_kofia_baseline,
    fetch_naver_yields,
    fetch_yahoo_yields,
    market_is_open,
    parse_admin_csv,
    safe_provider,
)

st.set_page_config(page_title="KTB Curve Desk", page_icon="📈", layout="wide")
st_autorefresh(interval=15_000, key="market-refresh")

st.markdown(
    """
<style>
  .stApp { background: #07111f; color: #e5edf7; }
  [data-testid="stHeader"] { background: rgba(7,17,31,.88); }
  .block-container { max-width: 1480px; padding-top: 1.4rem; }
  .hero { padding: 1.1rem 1.2rem; border: 1px solid #18314f; border-radius: 18px;
          background: radial-gradient(circle at top right,#123453 0,#0b1c30 42%,#091523 100%); }
  .eyebrow { color:#51d6c3; font-size:.78rem; letter-spacing:.14em; font-weight:700; }
  .hero h1 { margin:.2rem 0; font-size:clamp(1.55rem,3vw,2.55rem); }
  .subtle { color:#8fa6c0; font-size:.88rem; }
  .badge { display:inline-block; padding:.16rem .48rem; border-radius:999px; font-size:.68rem;
           font-weight:800; letter-spacing:.04em; margin-left:.3rem; }
  .LIVE { background:#0d4d43; color:#63f2d6; }
  .DELAYED { background:#594413; color:#ffd56a; }
  .CSV { background:#1f3b70; color:#a8c7ff; }
  .EMPTY { background:#364152; color:#cbd5e1; }
  .alert-card { border-left:4px solid #ef4444; padding:.72rem 1rem; margin:.55rem 0;
                background:#101f31; border-radius:0 12px 12px 0; }
  .alert-card strong { color:#f6f9fc; } .alert-card span { color:#b8c7d9; font-size:.88rem; }
  .signal { display:flex; gap:.8rem; align-items:center; background:#0d1c2d; padding:1rem;
            border:1px solid #1c3551; border-radius:14px; }
  .signal-dot { width:23px; height:23px; border-radius:50%; box-shadow:0 0 18px currentColor; }
  .metric-chip { color:#8fa6c0; font-size:.74rem; }
  div[data-testid="stMetric"] { background:#0d1c2d; border:1px solid #1b324c; padding:.78rem;
                                border-radius:14px; }
  div[data-testid="stForm"] { background:#0b1929; border:1px solid #1b324c; border-radius:16px; padding:1rem; }
  @media (max-width: 700px) { .block-container { padding:.8rem .65rem; } .hero { padding:.9rem; } }
</style>
""",
    unsafe_allow_html=True,
)


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


@st.cache_data(ttl=300, show_spinner=False)
def external_sources(bok_key: str) -> tuple[dict, dict, dict, dict, dict]:
    if os.getenv("DASHBOARD_OFFLINE") == "1":
        return {}, {}, {}, {}, {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        ecos_job = pool.submit(safe_provider, lambda: fetch_ecos_yields(bok_key), {})
        yahoo_job = pool.submit(safe_provider, fetch_yahoo_yields, {})
        naver_job = pool.submit(safe_provider, fetch_naver_yields, ({}, {}))
        kofia_job = pool.submit(safe_provider, fetch_kofia_baseline, {})
    naver, naver_previous = naver_job.result()
    return ecos_job.result(), yahoo_job.result(), naver, naver_previous, kofia_job.result()


@st.cache_resource
def shared_override() -> dict[str, float]:
    return {}


def metric_value(value: float | None, suffix: str = "", digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}{suffix}"


def spread_metric(value: float | None, suffix: str = " bp") -> str:
    if value is None:
        return "—"
    return f"{value:+.1f}{suffix}"


now = datetime.now(KST)
month = now.strftime("%Y-%m")
storage_key = f"ktb-curve-budget-{month}"
default_budget = {"month": month, "limit": 0.0, "spent": 0.0, "duration_gap": 0.0}
if "budget" not in st.session_state:
    st.session_state.budget = default_budget.copy()
    st.session_state.budget_loaded = False

stored = streamlit_js_eval(
    js_expressions=f"localStorage.getItem({json.dumps(storage_key)})",
    key=f"budget-load-{month}",
)
if stored and not st.session_state.budget_loaded:
    try:
        parsed = json.loads(stored)
        if parsed.get("month") == month:
            st.session_state.budget = {**default_budget, **parsed}
    except (TypeError, json.JSONDecodeError):
        pass
    st.session_state.budget_loaded = True

bok_key = secret("BOK_API_KEY") or secret("ECOS_API_KEY") or os.getenv("BOK_API_KEY", "") or "sample"
ecos, yahoo, naver, naver_previous, kofia = external_sources(bok_key)
snapshot = build_snapshot(
    now,
    ecos=ecos,
    yahoo=yahoo,
    naver=naver,
    naver_previous=naver_previous,
    kofia=kofia,
    admin_override=shared_override(),
)
values = snapshot.values
spreads = calculate_spreads(values)
light_code, light_label, light_color = traffic_light(spreads)
foreign_net = int(values["KTBF10_FOREIGN_NET"]) if "KTBF10_FOREIGN_NET" in values else None
alerts = evaluate_alerts(spreads, snapshot.futures_5m_change, foreign_net)

previous_alerts = set(st.session_state.get("active_alert_ids", []))
new_alerts, current_ids = newly_triggered(previous_alerts, alerts)
st.session_state.active_alert_ids = list(current_ids)
st.session_state.setdefault("guide_log", [])
for alert in new_alerts:
    stamp = now.strftime("%H:%M:%S")
    st.session_state.guide_log.insert(
        0,
        {
            "time": stamp,
            "title": alert.title,
            "guidance": alert.guidance,
            "gap": float(st.session_state.budget.get("duration_gap", 0)),
        },
    )
    st.toast(alert.title)
st.session_state.guide_log = st.session_state.guide_log[:30]

all_ids = set(INSTRUMENTS)
observed = snapshot.observations
status_counts = {status: sum(o.status == status for o in observed.values()) for status in STATUS_LABELS}
empty_count = len(all_ids - set(observed))
if empty_count:
    status_counts["EMPTY"] = empty_count
badge_html = " ".join(
    f'<span class="badge {status}">{STATUS_LABELS[status]} {count}</span>'
    for status, count in status_counts.items()
    if count
)
market_label = "장중 갱신" if market_is_open(now) else "장마감/공식일별 기준"
st.markdown(
    f"""
<div class="hero">
  <div class="eyebrow">INSURANCE FIXED INCOME · CURVE DESK</div>
  <h1>국고채 전 만기 일드 커브 & 기간 프리미엄</h1>
  <div class="subtle">{market_label} · 최종 갱신 {snapshot.generated_at:%Y-%m-%d %H:%M:%S} KST {badge_html}</div>
</div>
""",
    unsafe_allow_html=True,
)

st.info(
    "가짜 데이터는 표시하지 않습니다. 국고채는 한국은행 ECOS 공식 일별금리와 네이버페이증권/Refinitiv 장중값이 연결될 때만 표시하고, "
    "회사채·특수채·국채선물은 실데이터 또는 관리자 CSV가 없으면 빈값으로 둡니다.",
    icon="ℹ️",
)

if alerts:
    st.markdown("### 현재 활성 경보")
    for alert in alerts:
        st.markdown(
            f'<div class="alert-card"><strong>{alert.title}</strong><br><span>{alert.guidance}</span></div>',
            unsafe_allow_html=True,
        )
else:
    st.success("활성 경보가 없습니다. 단, 빈값 항목은 경보 판단에서 제외됩니다.")

st.markdown("### 집행 컨트롤러")
budget = st.session_state.budget
with st.form("execution-form"):
    c1, c2, c3, c4 = st.columns([1, 1, 1, 0.8])
    with c1:
        limit = st.number_input("당월 총 집행 한도(억원)", min_value=0.0, value=float(budget["limit"]), step=10.0)
    with c2:
        execution = st.number_input("당일 집행 금액(억원)", min_value=0.0, value=0.0, step=1.0)
    with c3:
        duration_gap = st.number_input("목표 듀레이션 갭(년)", value=float(budget["duration_gap"]), step=0.1)
    with c4:
        st.write("")
        submitted = st.form_submit_button("집행 업데이트", use_container_width=True, type="primary")
if submitted:
    try:
        result = apply_execution(limit, float(budget["spent"]), execution)
        st.session_state.budget = {
            "month": month,
            "limit": result.limit,
            "spent": result.spent,
            "duration_gap": duration_gap,
        }
        payload = json.dumps(st.session_state.budget, ensure_ascii=False)
        streamlit_js_eval(
            js_expressions=f"localStorage.setItem({json.dumps(storage_key)}, {json.dumps(payload)})",
            key=f"budget-save-{now.timestamp()}",
        )
        st.success(f"{execution:,.1f}억원 집행을 반영했습니다.")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

budget = st.session_state.budget
remaining = max(float(budget["limit"]) - float(budget["spent"]), 0)
m1, m2, m3, m4 = st.columns(4)
m1.metric("월 한도", f"{budget['limit']:,.1f} 억원")
m2.metric("누적 집행", f"{budget['spent']:,.1f} 억원")
m3.metric("잔여 가능액", f"{remaining:,.1f} 억원")
m4.metric("목표 듀레이션 갭", f"{budget['duration_gap']:+.1f} 년")

st.markdown("### 메인 커브")
left, right = st.columns([3, 1])
current_curve = [values.get(f"KTB_{tenor}Y") for tenor in TENORS]
previous_curve = [snapshot.previous_close.get(f"KTB_{tenor}Y") for tenor in TENORS]
with left:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[f"{x}Y" for x in TENORS],
            y=current_curve,
            mode="lines+markers",
            name="현재 5분 SMA / ECOS 공식값",
            line=dict(color="#52e0c4", width=4),
            marker=dict(size=10),
            hovertemplate="%{x}<br>%{y:.3f}%<extra>현재</extra>",
            connectgaps=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[f"{x}Y" for x in TENORS],
            y=previous_curve,
            mode="lines+markers",
            name="전일/최근 공식 기준",
            line=dict(color="#7893b2", width=2, dash="dash"),
            marker=dict(size=7),
            hovertemplate="%{x}<br>%{y:.3f}%<extra>기준</extra>",
            connectgaps=False,
        )
    )
    fig.update_layout(
        height=450,
        margin=dict(l=25, r=15, t=20, b=20),
        paper_bgcolor="#07111f",
        plot_bgcolor="#0a1727",
        font=dict(color="#b8c7d9"),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.08),
        yaxis=dict(title="수익률(%)", gridcolor="#18304b", tickformat=".2f"),
        xaxis=dict(title="만기", gridcolor="#18304b"),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
with right:
    st.markdown(
        f"""
    <div class="signal">
      <div class="signal-dot" style="background:{light_color};color:{light_color}"></div>
      <div><div class="metric-chip">기간 프리미엄 상태</div><strong>{light_code} · {light_label}</strong></div>
    </div>
    """,
        unsafe_allow_html=True,
    )
    st.metric("30Y - 3Y", spread_metric(spreads["30Y-3Y"]))
    st.metric("30Y - 10Y", spread_metric(spreads["30Y-10Y"]))
    st.metric("20Y - 30Y", spread_metric(spreads["20Y-30Y"]))

st.markdown("### 스프레드 모니터")
spread_names = [
    "10Y-3Y",
    "AA0 5Y-국고 5Y",
    "AA0 10Y-국고 10Y",
    "특수 AAA 10Y-국고 10Y",
    "특수 AAA 20Y-국고 20Y",
    "특수 AAA 30Y-국고 30Y",
]
for start in range(0, len(spread_names), 3):
    cols = st.columns(3)
    for col, name in zip(cols, spread_names[start:start + 3]):
        col.metric(name, spread_metric(spreads[name]))

st.markdown("### 국채선물 · 외국인 수급")
f1, f2, f3, f4 = st.columns(4)
f1.metric("3년 국채선물", metric_value(values.get("KTBF3_PRICE"), digits=2))
f2.metric("10년 국채선물", metric_value(values.get("KTBF10_PRICE"), digits=2))
f3.metric("10Y - 3Y 가격 스프레드", spread_metric(spreads["선물 10Y-3Y"], suffix=""))
f4.metric("외인 10년 누적", "—" if foreign_net is None else f"{foreign_net:+,} 계약")

bottom_left, bottom_right = st.columns([1.5, 1])
with bottom_left:
    st.markdown("### 액션 가이드 로그")
    if st.session_state.guide_log:
        for event in st.session_state.guide_log:
            st.markdown(
                f"**{event['time']} · {event['title']}**  \n{event['guidance']}  \n"
                f"<span class='subtle'>목표 듀레이션 갭 {event['gap']:+.1f}년</span>",
                unsafe_allow_html=True,
            )
            st.divider()
    else:
        st.caption("이번 접속에서 발생한 액션 가이드가 없습니다.")
with bottom_right:
    st.markdown("### 데이터 출처")
    rows = []
    for key in sorted(INSTRUMENTS):
        observation = observed.get(key)
        meta = INSTRUMENTS[key]
        rows.append(
            {
                "자산": meta["label"],
                "값": "" if observation is None or observation.value is None else observation.value,
                "상태": "실데이터 없음" if observation is None else STATUS_LABELS.get(observation.status, observation.status),
                "출처": "" if observation is None else observation.source,
                "기준시각": "" if observation is None or observation.as_of is None else observation.as_of.strftime("%m-%d %H:%M"),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=330)

with st.expander("관리자 · 실데이터 CSV 업로드"):
    configured_password = secret("ADMIN_PASSWORD")
    password = st.text_input("관리자 비밀번호", type="password")
    upload = st.file_uploader("CSV", type=["csv"], help="as_of_kst,instrument_id,value,unit,quote_type")
    if st.button("CSV 값 적용", disabled=not upload):
        if not configured_password:
            st.error("배포 Secrets에 ADMIN_PASSWORD가 설정되어 있지 않습니다.")
        elif password != configured_password:
            st.error("관리자 비밀번호가 올바르지 않습니다.")
        else:
            try:
                parsed = parse_admin_csv(upload.getvalue())
                shared_override().clear()
                shared_override().update(parsed)
                st.success(f"{len(parsed)}개 값을 서버 메모리에 적용했습니다.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

st.caption(
    "본 화면은 투자판단 참고용입니다. 한국은행 ECOS는 공식 일별 시장금리이며 장중 실시간 틱 데이터가 아닙니다. "
    "실데이터가 연결되지 않은 항목은 빈값으로 표시되며, 최종 투자 결정 전 공식 원천을 재확인하세요."
)
