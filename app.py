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
    KST, build_snapshot, fetch_kofia_baseline, fetch_yahoo_yields, market_is_open, parse_admin_csv, safe_provider,
    fetch_naver_yields,
)

st.set_page_config(page_title="KTB Curve Desk", page_icon="📈", layout="wide")
st_autorefresh(interval=15_000, key="market-refresh")

st.markdown("""
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
  .LIVE { background:#0d4d43; color:#63f2d6; } .DELAYED { background:#594413; color:#ffd56a; }
  .MOCK { background:#532332; color:#ff91ad; }
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
""", unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner=False)
def external_sources() -> tuple[dict, dict, dict, dict]:
    if os.getenv("DASHBOARD_OFFLINE") == "1":
        return {}, {}, {}, {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        yahoo_job = pool.submit(safe_provider, fetch_yahoo_yields)
        naver_job = pool.submit(safe_provider, fetch_naver_yields, ({}, {}))
        kofia_job = pool.submit(safe_provider, fetch_kofia_baseline)
    naver, naver_previous = naver_job.result()
    return yahoo_job.result(), naver, naver_previous, kofia_job.result()


@st.cache_resource
def shared_override() -> dict[str, float]:
    return {}


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


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

yahoo, naver, naver_previous, kofia = external_sources()
snapshot = build_snapshot(
    now, yahoo=yahoo, naver=naver, naver_previous=naver_previous,
    kofia=kofia, admin_override=shared_override(),
)
values = snapshot.values
spreads = calculate_spreads(values)
light_code, light_label, light_color = traffic_light(spreads)
alerts = evaluate_alerts(spreads, snapshot.futures_5m_change, int(values["KTBF10_FOREIGN_NET"]))

previous_alerts = set(st.session_state.get("active_alert_ids", []))
new_alerts, current_ids = newly_triggered(previous_alerts, alerts)
st.session_state.active_alert_ids = list(current_ids)
st.session_state.setdefault("guide_log", [])
for alert in new_alerts:
    stamp = now.strftime("%H:%M:%S")
    st.session_state.guide_log.insert(0, {
        "time": stamp, "title": alert.title, "guidance": alert.guidance,
        "gap": float(st.session_state.budget.get("duration_gap", 0)),
    })
    st.toast(alert.title)
st.session_state.guide_log = st.session_state.guide_log[:30]

market_label = "장중 갱신" if market_is_open(now) else "장 마감 · 값 고정"
status_counts = {status: sum(o.status == status for o in snapshot.observations.values()) for status in STATUS_LABELS}
badge_html = " ".join(
    f'<span class="badge {status}">{STATUS_LABELS[status]} {count}</span>'
    for status, count in status_counts.items() if count
)
st.markdown(f"""
<div class="hero">
  <div class="eyebrow">INSURANCE FIXED INCOME · CURVE DESK</div>
  <h1>국고채 전 만기 일드 커브 & 기간 프리미엄</h1>
  <div class="subtle">{market_label} · 최종 갱신 {snapshot.generated_at:%Y-%m-%d %H:%M:%S} KST {badge_html}</div>
</div>
""", unsafe_allow_html=True)

if alerts:
    st.markdown("### 현재 활성 경보")
    for alert in alerts:
        st.markdown(
            f'<div class="alert-card"><strong>{alert.title}</strong><br><span>{alert.guidance}</span></div>',
            unsafe_allow_html=True,
        )
else:
    st.success("활성 경보가 없습니다. 현재 커브는 설정된 정상 범위 안에 있습니다.")

st.markdown("### 집행 컨트롤러")
budget = st.session_state.budget
with st.form("execution-form"):
    c1, c2, c3, c4 = st.columns([1, 1, 1, .8])
    with c1:
        limit = st.number_input("당월 총 집행 한도(억원)", min_value=0.0, value=float(budget["limit"]), step=10.0)
    with c2:
        execution = st.number_input("당일 집행 금액(억원)", min_value=0.0, value=0.0, step=1.0)
    with c3:
        duration_gap = st.number_input("목표 듀레이션 갭(년)", value=float(budget["duration_gap"]), step=0.1)
    with c4:
        st.write("")
        submitted = st.form_submit_button("집행 업데이트", width="stretch", type="primary")
if submitted:
    try:
        result = apply_execution(limit, float(budget["spent"]), execution)
        st.session_state.budget = {
            "month": month, "limit": result.limit, "spent": result.spent,
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
current_curve = [values[f"KTB_{tenor}Y"] for tenor in TENORS]
previous_curve = [snapshot.previous_close[f"KTB_{tenor}Y"] for tenor in TENORS]
with left:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[f"{x}Y" for x in TENORS], y=current_curve, mode="lines+markers",
        name="현재 5분 SMA", line=dict(color="#52e0c4", width=4), marker=dict(size=10),
        hovertemplate="%{x}<br>%{y:.3f}%<extra>현재</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=[f"{x}Y" for x in TENORS], y=previous_curve, mode="lines+markers",
        name="전일 종가", line=dict(color="#7893b2", width=2, dash="dash"), marker=dict(size=7),
        hovertemplate="%{x}<br>%{y:.3f}%<extra>전일</extra>",
    ))
    fig.update_layout(
        height=450, margin=dict(l=25, r=15, t=20, b=20), paper_bgcolor="#07111f", plot_bgcolor="#0a1727",
        font=dict(color="#b8c7d9"), hovermode="x unified", legend=dict(orientation="h", y=1.08),
        yaxis=dict(title="수익률 (%)", gridcolor="#18304b", tickformat=".2f"),
        xaxis=dict(title="만기", gridcolor="#18304b"),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
with right:
    st.markdown(f"""
    <div class="signal">
      <div class="signal-dot" style="background:{light_color};color:{light_color}"></div>
      <div><div class="metric-chip">기간 프리미엄 상태</div><strong>{light_code} · {light_label}</strong></div>
    </div>
    """, unsafe_allow_html=True)
    st.metric("30Y - 3Y", f"{spreads['30Y-3Y']:+.1f} bp")
    st.metric("30Y - 10Y", f"{spreads['30Y-10Y']:+.1f} bp")
    st.metric("20Y - 30Y", f"{spreads['20Y-30Y']:+.1f} bp")

st.markdown("### 스프레드 모니터")
spread_names = [
    "10Y-3Y", "AA0 5Y-국고 5Y", "AA0 10Y-국고 10Y",
    "특수 AAA 10Y-국고 10Y", "특수 AAA 20Y-국고 20Y", "특수 AAA 30Y-국고 30Y",
]
for start in range(0, len(spread_names), 3):
    cols = st.columns(3)
    for col, name in zip(cols, spread_names[start:start + 3]):
        col.metric(name, f"{spreads[name]:+.1f} bp")

st.markdown("### 국채선물 · 외국인 수급")
f1, f2, f3, f4 = st.columns(4)
f1.metric("3년 국채선물", f"{values['KTBF3_PRICE']:.2f}", help="MOCK")
f2.metric("10년 국채선물", f"{values['KTBF10_PRICE']:.2f}", delta=f"5분 {snapshot.futures_5m_change:+.2f}", help="MOCK")
f3.metric("10Y - 3Y 가격 스프레드", f"{spreads['선물 10Y-3Y']:+.3f}", help="MOCK")
f4.metric("외인 10년 누적", f"{int(values['KTBF10_FOREIGN_NET']):+,} 계약", help="MOCK")

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
    for key, observation in snapshot.observations.items():
        label = INSTRUMENTS.get(key, {}).get("label", key.replace("_", " "))
        rows.append({
            "자산": label, "값": observation.value, "상태": STATUS_LABELS[observation.status],
            "출처": observation.source, "기준시각": observation.as_of.strftime("%m-%d %H:%M"),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=330)

with st.expander("관리자 · KOFIA/민평 기준 CSV 업로드"):
    configured_password = secret("ADMIN_PASSWORD")
    password = st.text_input("관리자 비밀번호", type="password")
    upload = st.file_uploader("기준 CSV", type=["csv"], help="as_of_kst,instrument_id,value,unit,quote_type")
    if st.button("기준값 적용", disabled=not upload):
        if not configured_password:
            st.error("배포 Secrets에 ADMIN_PASSWORD가 설정되지 않았습니다.")
        elif password != configured_password:
            st.error("관리자 비밀번호가 올바르지 않습니다.")
        else:
            try:
                parsed = parse_admin_csv(upload.getvalue())
                shared_override().clear()
                shared_override().update(parsed)
                st.success(f"{len(parsed)}개 기준값을 서버 메모리에 적용했습니다.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

st.caption(
    "본 화면은 투자판단 참고용이며 무료 외부 소스의 지연·누락 시 모의 데이터가 사용됩니다. "
    "MOCK 표기 값은 실제 체결·호가가 아니며 최종 투자 결정 전 공식 원천을 확인하세요."
)
