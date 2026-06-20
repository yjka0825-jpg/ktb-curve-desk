# KTB Curve Desk

보험사 장부가 계정 운용역을 위한 국고채 전 만기 일드 커브·기간 프리미엄 모니터입니다.

## 핵심 기능

- 3Y~30Y 현재 5분 SMA 커브와 전일 종가 비교
- 국고·AA0 회사채·AAA 특수채 스프레드 및 국채선물/외국인 수급 모니터
- 기간 프리미엄, 초장기 역전, 20Y 벨리, 선물 급변 경보와 액션 가이드
- Yahoo 우선, 네이버페이 증권·Refinitiv 장중 시계열 보완, KOFIA 기반 모킹 순의 공급 엔진
- LIVE/지연/MOCK 출처 배지와 KST 기준시각
- 브라우저별 월 집행 한도·누적액 저장
- 비밀번호 보호 관리자 CSV 기준값 업로드

## 로컬 실행

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
streamlit run app.py
```

## CSV 기준값

`sample_baseline.csv` 형식을 사용합니다. 필수 열은 다음과 같습니다.

`as_of_kst,instrument_id,value,unit,quote_type`

업로드값은 서버 메모리에만 보관되므로 재시작·재배포 시 내장 기준값으로 복구됩니다.

## Streamlit Community Cloud 배포

1. 이 저장소를 GitHub 공개 저장소에 푸시합니다.
2. Streamlit Community Cloud에서 `app.py`를 진입점으로 선택합니다.
3. App settings → Secrets에 아래 값을 설정합니다.

```toml
ADMIN_PASSWORD = "충분히 긴 관리자 비밀번호"
```

4. 재부팅 후 공개 URL에서 데이터 출처 배지와 모바일 레이아웃을 확인합니다.

## 주의

무료 원천의 누락·지연 시 모의 데이터가 작동합니다. `MOCK` 값은 실제 체결·호가가 아니며 투자판단 전 공식 원천을 확인해야 합니다.

네이버페이 증권 공개 데이터는 5분 단위로만 재조회하여 서비스 부하를 제한합니다. 원천 응답에는 레피니티브 기준 및 실시간 여부가 포함되며, 장 마감 후에는 `지연`으로 표시합니다.
