# 사업계획서 수정안 (Business Proposal, 2026-07-24 판 기준)

> 이 수정안은 **사업계획서 v2 (2026-10-27)** 에 모두 반영되었습니다. 변경 내역은 v2의 Appendix D에 있습니다.

검토 보고서(2026-10-27)의 지적을 반영해 PDF에 그대로 옮길 수 있는 문구와 표를 정리했습니다.
숫자는 이 저장소의 코드(`synapse_h/finance.py`, `scripts/run_twin_experiment.py`)로 다시 계산할 수 있습니다.

## P0-1. 첫해 자금 요청과 손익 계획 연결 (p.24, p.35)

**문제:** 첫해 요청 자금은 ₩70M인데, Table 18의 첫해 계획은 매출 ₩150M · 매출원가 ₩50M · 영업비용 ₩340M,
즉 EBITDA −₩240M입니다. 차액 ₩170M을 어떻게 메우는지가 없습니다.

**현금 연결 결과** (Table 18의 연간 수치를 월별로 균등 분배, ₩70M에서 시작; 앱의 *시장·사업 모델 → 자금 조달 연결표*에서 조절 가능):

| 구매대금 회수 지연 | 최저 현금 잔고 | 시점 | 추가 조달 필요액 |
|---|---|---|---|
| 0개월 (즉시 입금) | −₩350M | 24개월 차 | ₩350M |
| 2개월 | −₩710M | 38개월 차 | ₩710M |
| 4개월 | −₩1,290M | 40개월 차 | ₩1,290M |
| 6개월 | −₩1,890M | 54개월 차 | ₩1,890M |

회수 지연이 없어도 2년 차 말까지 누적 손실(−₩240M −₩180M)을 메울 ₩350M이 더 필요합니다. 3년 차에 흑자로
바뀌어도 매출이 빠르게 늘면 공공기관의 대금 지급이 늦는 동안 미수금이 쌓여 운전자본이 크게 필요해집니다.

**추가할 표 (한 장):**

| 구분 | Y1 | Y2 | Y3 |
|---|---|---|---|
| 요청 자금 (이번 경진대회·초기 투자) | ₩70M | | |
| 창업자 부담·현물 기여 (무급 개발 등, 금액 환산) | | | |
| 정부지원·R&D 과제 (신청 예정 사업명) | | | |
| 유료 파일럿 매출 (현금 입금 시점 기준) | | | |
| 월 평균 현금 소진액 (인건비·외주·클라우드·법무) | | | |
| 최소 운영자금 (6개월치 소진액) | | | |
| 추가 조달 필요액 및 시점 | | | |
| 매출 지연 시 대응 (인력 채용 연기, 경로 축소) | | | |

**권장 문구:** "₩70M은 12개월 검증 단계(프로토타입·보안·임상 자문)의 직접 비용이며, Table 18의 영업비용에 포함된
인건비 등은 창업자 무급 기여와 2년 차 시드 조달로 충당한다. 구매대금 회수 지연을 4개월로 가정하면 손익분기
이후에도 최대 약 ₩1.3B의 운전자본이 필요하므로, 3년 차 이전에 추가 조달을 계획한다."

## P0-2. 첫 시장의 실제 수요 근거 (p.3, p.6–8)

**문제:** 119 출동 332만 건, 응급실 방문 784만 건은 문제의 크기를 보여 주지만, 첫 시장인 *병원 간 전원* 건수가 아닙니다.

**추가할 근거 (확인된 문헌):** 국가응급의료상황실이 2017–2019년 받은 전원 조정 요청 14,003건 중 분석된 10,222건에서
81.2%(8,297건)가 조정에 성공했고, 요청 사유는 의료인력 부족 59.8%, 중환자실 병상 부족 30.8%였으며, 지연은 병원 자원
부족과 유의하게 연관되었습니다 (BMC Emergency Medicine 2023, doi:10.1186/s12873-023-00782-1).

**함께 적을 한계:** 병상·인력이 실제로 없어서 생기는 지연은 정보 정리로 해결되지 않습니다. 제품이 줄일 수 있는 것은
*탐색·연락·재설명*에 드는 시간입니다.

**수집 계획:** 목표 지역의 월간 전원 건수, 요청→확정 시간, 케이스당 연락 수, 거절 사유를 참여 병원 2주 익명 집계로
확인합니다 (질문 목록: [VALIDATION_PLAN.md](VALIDATION_PLAN.md) §2).

## P1-1. 가격과 구매 가능성 (p.19, Table 12)

TAM 계산(17 × ₩250M + 181 × ₩60M + 233 × ₩24M = ₩20.70B)은 산술적으로 맞습니다. 단가가 실제 지불 의사인지,
지역 라이선스와 병원 라이선스의 예산 주체가 어떻게 나뉘는지는 검증되지 않았습니다. 표 아래에 다음을 추가합니다.

> 단가는 경영진 가정이다. 지역 상황실·상급병원·의뢰 병원 구매 책임자 인터뷰(목표 10명 이상)로 예산 출처, 구매 절차,
> 연간 지불 의사, 보안·연동 비용 부담자를 확인하기 전까지 매출 전망은 가설로 표기한다.

인터뷰 질문: [VALIDATION_PLAN.md](VALIDATION_PLAN.md) §3.

## P1-2. 5개년 매출 역산 (p.24, Table 18)

제안서의 연도별 상업 동인(1년 차 유료 파일럿 1건 … 5년 차 9개 지역·150개 노드)을 `고객 수 × 단가 × 인식 기간`으로 다시
쌓으면 다음과 같습니다 (₩M, 신규 라이선스는 평균 반년치만 인식, 노드는 고급:기본 ≈ 6:4 가정, 연동비 ₩15M/병원).

| 연도 | 지역 | 고급 노드 | 기본 노드 | 파일럿 | 연동비 | 역산 합계 | 제안서 계획 | 차이 |
|---|---|---|---|---|---|---|---|---|
| Y1 | 0 | 0 | 0 | 125 | 30 | **155** | 150 | +5 |
| Y2 | 125 | 150 | 84 | 0 | 150 | **509** | 720 | −211 |
| Y3 | 375 | 600 | 204 | 125 | 195 | **1,499** | 1,950 | −451 |
| Y4 | 875 | 1,710 | 456 | 125 | 675 | **3,841** | 4,750 | −909 |
| Y5 | 1,750 | 3,960 | 1,056 | 125 | 1,200 | **8,091** | 9,200 | −1,109 |

계획 매출은 *모든 신규 계약이 1월 1일에 시작된다*고 가정할 때에 가깝습니다. 둘 중 하나로 맞춥니다.

1. 계획 매출을 역산 합계로 낮추고 손익분기 시점을 다시 계산하거나,
2. 연도별 신규 계약 수·계약 시점·평균 영업기간·전환율·갱신율을 근거와 함께 표로 제시합니다.

공공 구매 지연 시나리오(도입 속도 65%)는 앱의 *5개년 기본 시나리오* 슬라이더로 계산할 수 있습니다.

## P1-3. 경쟁 우위 비교 기준 (p.20–21, Table 14)

같은 기준으로 비교표를 다시 만듭니다: 데이터 출처, 병원 간 워크플로, 환자별 역량 제약, 추천 설명, 다중 환자 배정,
규제·보안, 국내 연동, 실제 도입 비용. 차별화 근거는 기능 목록이 아니라 고객 인터뷰에서 확인된 미충족 요구로 남깁니다.

## 규제·표준 최신화 (p.29–30)

| 위치 | 현재 문구 | 수정 문구 |
|---|---|---|
| p.29 §8.1 | "Korea's Digital Medical Products Act took effect on 21 February 2025." | "Korea's Digital Medical Products Act (Act No. 20139) was enacted on 23 January 2024 and took effect on **24 January 2025** together with its enforcement decree; Articles 33–35 took effect on 24 January 2026." — 2025-02-21은 이 법의 개정이 아니라 다른 법률(법률 제20331호) 개정에 따른 타법개정 시행일입니다. 원래 [17] 링크(lsiSeq=260593)가 그 개정이 반영된 판을 가리켜 생긴 혼동일 가능성이 높아, 링크를 법령 고정 주소(law.go.kr/법령/디지털의료제품법)로 바꿉니다 |
| p.29 §8.1 뒤 | — | "On 26 June 2026 MFDS issued a guideline on approval and review of change-management plans for digital medical devices, which lets pre-approved post-market changes such as planned AI model updates proceed without a new review; on 27 July 2026 it amended the approval and review regulation (MFDS Notice No. 2026-54) to specify when clinical-trial data for digital medical device software may be waived or deemed partly submitted; and on 30 September 2026 it issued a guideline for professional-use digital medical device software — software patients use under a professional's diagnosis or supervision. Synapse-H is clinician-facing, so the last guideline matters mainly for how MFDS scopes intended use and required warnings." |
| p.12 §3.1, Table 25 | "FHIR is the interoperability spine … versioned FHIR interfaces" | "The prototype emits FHIR R5-shaped bundles that pass a structural self-check. Before any live connection they will be validated with the official FHIR validator and mapped to the **KR Core** profiles and code systems published by the Korea Health Information Service, plus the receiving institution's implementation guide." |
| Table 25 "Adaptive model update" | "approved change-control plan" | "pre-approved change-management plan (MFDS guideline, 26 June 2026); monitoring" |

확인 결과 (2026-10-27, 원문 인용 검색 기준. 이 세션에서는 국가법령정보센터·식약처 사이트에 직접 접속할 수 없었습니다):

| 항목 | 확인 내용 | 출처 |
|---|---|---|
| 디지털의료제품법 | 법률 제20139호, 2024.1.23 제정, 2025.1.24 시행, 제33–35조는 2026.1.24 시행. 2025.2.21은 법률 제20331호 개정에 따른 타법개정 | 국가법령정보센터 법령 본문·연혁, LBOX |
| 변경관리 계획서 가이드라인 | 2026.6.26 제정 「디지털의료기기 변경관리 계획서 허가·심사 가이드라인」 | 식약처 보도참고 (재게시), 메디컬타임즈 |
| 허가·심사 규정 개정 | 고시 제2026-54호, 2026.7.27 시행, 소프트웨어 임상시험 자료 면제·간주 기준 구체화 | 국가법령정보센터 행정규칙, 데일리팜, 법률신문 |
| 전문가용 SW 가이드라인 | 2026.9.30 제정. 의료인의 진단·지시·감독 아래 **환자가 쓰는** 소프트웨어 대상 | 식약처 보도참고, 복지타임즈 등 |

제출 전에는 국가법령정보센터와 식약처 누리집 원문에서 한 번 더 확인하세요.

## 합성 시뮬레이션 표 교체 (p.16, Table 9)

Table 9는 이전 프로토타입의 수치입니다. 현재 코드에서 재현되는 결과로 교체합니다
(`python scripts/run_twin_experiment.py`, 20,000 짝지은 에피소드, seed 2026–2035; 원본: `results/twin_baseline.md`).
정책은 관찰 가능한 정보만 사용하도록 수정되었습니다 ([DECISIONS.md](DECISIONS.md) D5).

| 지표 | Nearest appropriate | Synapse-H | 짝지은 차이 (10 seed 평균, 95% CI) |
|---|---|---|---|
| 1순위 수용률 | 64.1% | 69.9% | +5.5%p [+5.3, +5.7] |
| 평균 연락 횟수 | 1.50 | 1.43 | −0.07 [−0.08, −0.07] |
| 평균 승인 시간 | 6.77분 | 6.31분 | −0.45분 [−0.46, −0.43] |
| 평균 이송 시간 | 16.50분 | 16.82분 | +0.31분 [+0.31, +0.31] |
| 승인 + 이송 | 23.27분 | 23.13분 | −0.14분 [−0.15, −0.12] |

(단일 실행 값은 seed 2026.) 문장도 함께 바꿉니다: "+8.6 percentage points"
→ "+5.5 percentage points (95% CI 5.3–5.7 across 10 seeds; simulation randomness only)". p.17 Table 11의 파일럿 목표
"≥8 percentage-point improvement"는 근거가 이 시뮬레이션이므로 "≥5 pp, to be finalised with partners"로 낮추거나 근거를 따로 밝힙니다.

## 표현 정리 (전체)

| 현재 표현 | 수정 표현 | 이유 |
|---|---|---|
| predicted acceptance probability | acceptance **score** (synthetic coefficients, not calibrated) | 실제 수용 빈도로 보정되지 않음 |
| FHIR-ready platform | prototype that emits FHIR R5-shaped bundles | 공식 검증·KR Core 미적용 |
| two interface prototypes | deployed web and mobile prototypes on synthetic data: https://hermesnode.streamlit.app/ · https://synapse-h-mobile.streamlit.app/ | 실제 배포 앱이 있음 |
| Controlled pilot (앱 화면) | synthetic demo | 실제 기관 파일럿이 아님 (앱 수정 완료) |
| NLP extraction | rule-based extraction with negation/history handling and mandatory clinician confirmation | LLM이 아님 |

## 참고문헌 표기 (p.43–44)

PDF에서 링크 텍스트가 모두 "Official/source page"로 보여 출력본에서 출처를 알 수 없습니다. 각 항목을
`기관/저자. 문서명. 발행처, 발행일. DOI 또는 URL. (접속일)` 형식으로 바꿉니다. 예:

- Min HS, Sung HK, Choi G, Sung H, Lee M, Kim SJ, Ko E. *Operation of national coordinating service for interhospital transfer from emergency departments:
  experience and implications from Korea.* BMC Emergency Medicine. 2023 (published 10 Feb 2023). doi:10.1186/s12873-023-00782-1
- 국가법령정보센터. 디지털의료제품법 (법률 제20139호, 2024.1.23. 제정, 2025.1.24. 시행). https://www.law.go.kr/법령/디지털의료제품법 (2026-10-27 접속)


## 기여도 표기 (p.34, §10)

평가자가 본인의 실제 역량을 구분할 수 있게, 팀 계획 표 아래에 다음을 추가하는 것을 권장합니다.

> The prototype code was implemented with an AI coding assistant under the founder's direction; problem definition,
> product requirements, design decisions, validation planning and the business case are the founder's work.
