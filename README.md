# HERMES_NODE
SYNAPSE-H 프로젝트

**SYNAPSE-H — 응급 전원·병원 수용을 위한 사람 감독형 의사결정 지능 (Human-Supervised Decision Intelligence for Emergency Transfer and Hospital Acceptance)**

사업제안서의 MVP를 실행 가능한 웹 애플리케이션으로 구현했습니다.
의뢰서를 구조화하고, 목적지 준비도를 예측하며, 불확실성 아래에서 임상적으로 적합한 병원을
**설명 가능한 상위 3개 옵션**으로 제시합니다. **최종 결정은 항상 의료진이 내립니다.**

> ⚠️ 모든 병원·환자 값은 합성 예시입니다. 실제 환자 데이터나 실제 기관 정보를 쓰지 않으며, 임상 검증을 거치지 않았습니다.

## 실행

Python 3.10 이상이 필요합니다. 저장소 최상위 폴더(`HERMES_NODE`)에서 실행하세요.

Mac / Linux:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/streamlit_app.py      # http://localhost:8501
pytest                                  # 엔진 테스트
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

PowerShell에서 가상환경 활성화가 막히면 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`를 한 번 실행하세요.
다음부터는 가상환경 활성화와 `streamlit run` 두 줄만 실행하면 됩니다.

## 스마트폰에서 실행

앱을 Streamlit Community Cloud(무료)에 배포하면 휴대폰 브라우저에서 접속해 앱처럼 쓸 수 있습니다.
화면은 휴대폰 폭에 맞게 자동으로 바뀝니다.

1. https://share.streamlit.io 에 GitHub 계정으로 로그인합니다.
2. **Create app → Deploy a public app from GitHub**를 선택합니다.
3. Repository `Hyeonwoo01/HERMES_NODE`, Branch `main`, Main file path `app/streamlit_app.py`를 입력합니다.
4. 원하는 주소(예: `synapse-h.streamlit.app`)를 정하고 **Deploy**를 누릅니다. 첫 배포는 몇 분 걸립니다.
5. 휴대폰 브라우저로 그 주소에 접속한 뒤 홈 화면에 추가합니다.
   - iPhone (Safari): 공유 버튼 → **홈 화면에 추가**
   - Android (Chrome): 오른쪽 위 ⋮ → **홈 화면에 추가** 또는 **앱 설치**

`main`에 푸시하면 배포된 앱도 자동으로 갱신됩니다. 한동안 접속이 없으면 앱이 잠들며, 다시 열 때 깨우기 버튼을 누르면 됩니다.

## 모바일·태블릿 전용 앱 (`application_mobile.py`)

설정 메뉴 없이 **환자 정보를 넣고 의료진이 확인하면 바로 추천**하는 한 화면짜리 앱입니다.
기본 가중치, Controlled pilot 모드, 현재 한국 시각을 자동으로 씁니다.

```bash
streamlit run application_mobile.py
```

- **입력:** 의뢰 메모를 붙여 넣거나 항목별로 직접 입력합니다.
- **의료진 확인 (필수):** 메모에서 읽은 값을 근거 원문 표시와 함께 보여 주고, 빠지거나 범위를 벗어난 값을 표시합니다. "원문과 맞습니다"를 눌러야만 추천이 실행됩니다. 직접 입력한 값은 입력한 사람이 확인한 것으로 봅니다.
- **추천:** Top 3 병원이 바로 나오고, 병원마다 큰 "연락" 버튼이 있습니다. 1순위가 아닌 병원은 이유를 한 번 탭해서 고릅니다.
- **결과 기록:** 수용 / 거절을 누르고, 거절하면 그 병원을 빼고 다시 추천합니다. 받을 병원이 없으면 의료지도 연락을 안내합니다.

Streamlit Community Cloud에서 **Create app**으로 앱을 하나 더 만들고 Main file path를 `application_mobile.py`로 지정하면 별도 주소로 배포됩니다.
휴대폰·태블릿 브라우저에서 그 주소를 연 뒤 **홈 화면에 추가**하면 앱처럼 쓸 수 있습니다.

## 화면 구성

| 화면 | 제안서 근거 | 기능 |
|---|---|---|
| 개요 | Executive Case | 핵심 통계, 5단계 워크플로, 안전 경계 |
| 🚑 전원 오케스트레이터 | §2.1–2.3, Fig. 3–4 | ① Capture 의뢰서 입력 → ② Confirm 근거 원문 하이라이트와 의료진 확인 양식 → ③④ Match·Decide Top 3 카드(ETA, 예측 수용률·구간, 신뢰도, 피드 신선도, 순위 근거, WHY #1) → 선택 / 오버라이드(사유 필수) / 의료지도 호출 → 연락 결과(수용·거절) 기록, 거절 시 재순위 → ⑤ Learn 감사 추적 + FHIR R5 번들 |
| 🗺️ 지역 상황실 | §2.4, Fig. 5 | 활성 케이스, 1순위 수용률, 승인 시간 중앙값, 피드 지연 경보, 병원-케이스 네트워크, 병원 상태 편집(시뮬레이션) |
| 🧮 다중 환자 동시 배정 | §3.4 | 병상 용량 + 부하 집중(공정성) 벌점 하의 전역 최적 배정(헝가리안 알고리즘) vs 선착순 탐욕 배정 |
| 🧪 합성 디지털 트윈 | §4.2, 부록 A | Nearest-appropriate vs Synapse-H 짝지은 에피소드 시뮬레이션, 질환군별 결과, 민감도 분석, CSV 다운로드 |
| 🛡️ 감사 로그 · 안전 | §4.4, §8.4 | 추천·결정·오버라이드·연락 결과 로그(JSONL), 파일럿 지표, 모델 카드, 위해 통제 |
| 📈 시장 · 사업 모델 | §5–6, §10.3 | TAM/SAM/SOM 계산기, 가격 구조, 5개년 시나리오, ₩70M 사용 계획 |

사이드바에서 **운영 모드**(Controlled pilot / Shadow mode — 결정 후 추천 공개), 시뮬레이션 시각, 목적 함수 가중치 w₁–w₅를 조정할 수 있습니다.

## 데모 시나리오 (제안서 §4.5 최소 증거 목록)

- 뇌졸중 · 중증 외상 · 소아(한국어 의뢰서) · STEMI(한국어) — 정상 매칭
- **필수 항목 누락** → Abstain, 수동 입력 요구
- **범위 밖 입력(OOD)** (BP 400/200, SpO₂ 130%) → 범위 검사 실패, 랭킹 차단
- **수용 가능 병원 없음** (중증 화상) → `ESCALATE TO MEDICAL CONTROL`
- **피드 지연** — 지역 상황실에서 시간 경과를 시뮬레이션하면 15분 초과 피드는 하향 가중·경고, 60분 초과는 제외

## 엔진 구조 (`synapse_h/`)

| 모듈 | 역할 |
|---|---|
| `intake.py` | Transfer Intake — 스키마 제약 추출(근거 span·신뢰도), 범위 검증, Pre-KTAS 비추론, 의료진 확인 후 `CaseRecord` 생성. `Extractor` 프로토콜로 승인된 사설/온프레미스 모델로 교체 가능 |
| `capabilities.py` | Capability Registry — 임상 경로별 필수 역량(하드 제약), 소아 규칙 |
| `readiness.py` | Readiness Engine — 로지스틱 수용 예측, 피드 신선도 가중, 불확실성·신뢰도 라벨 |
| `optimizer.py` | Decision Optimizer — `w₁T + w₂C + w₃(1−A)R + w₄L + w₅U` 단일 케이스 랭킹·근거 생성·에스컬레이션, 다중 케이스 전역 배정 `+ λF(x)` |
| `fhir.py` | FHIR R5 형태 번들 (Patient, Encounter, Observation, Condition, ServiceRequest, Organization, Task) |
| `audit.py` | Safety & Audit — 추천·결정·오버라이드·연락 결과 로그와 모니터링 지표 |
| `twin.py` | 합성 디지털 트윈 — 공유 수용 난수로 두 정책 비교, 민감도 분석 |
| `data.py` | 가상 지역 네트워크(병원 8곳, 의뢰 기관 3곳)와 시나리오 |

디지털 트윈 결과는 계산적 타당성만 보여 줍니다. 사망률이나 임상 효과를 추정하지 않으며, 독립 구현이라 제안서 Table 9 수치와 다를 수 있습니다(같은 seed에서는 재현 가능).

