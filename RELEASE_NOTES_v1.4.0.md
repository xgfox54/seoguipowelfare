# 서귀포시 복지톡 AI 업무비서 v1.4.0

## 개요

v1.4.0은 모델 호출 횟수를 늘려 정확도를 보완하는 방식 대신 **검색과 검증을 프로그램 코드로 최대한 확정적으로 처리하고 LLM은 확보된 Evidence를 자연어로 정리하는 역할에 집중**하도록 답변 파이프라인을 재설계한 버전입니다.

## 핵심 변경

### 1. 사용자 질문을 사실 Evidence에서 제외

- `welfare_grounding.py`의 Grounding Validator가 검색된 복지DB 원문만 사실 근거로 사용합니다.
- 사용자가 질문에 입력한 금액·연도·사업명은 검색어/의도 분석에만 사용합니다.
- 예: `4인가구 200만원 지원 맞나요?`라고 질문해도 원문에 200만원이 없으면 해당 주장을 근거로 인정하지 않습니다.

### 2. E2B / E4B 배포판 모델 강제 고정

- E2B: `gemma4-e2b-it-qat.gguf`
- E4B: `gemma4-e4b.gguf` (Q4_K_M)
- `models` 폴더에서 먼저 발견된 모델을 자동 선택하지 않습니다.
- 현재 EXE 배포 변형과 GGUF 파일, llama-server가 실제 로딩한 모델이 일치하지 않으면 AI Ready 상태가 되지 않습니다.
- 다른 배포판의 모델을 API/CLI에서 강제로 요청해도 거부합니다.

### 3. Rule-based Query Planner

LLM Refiner를 기본 경로에서 제거하고 Python 코드가 다음을 추출합니다.

- 제도/사업 및 세부사업
- 대상 표현
- 업무단계(신청, 접수, 조사, 선정, 결정, 지급, 변경, 중지, 환수, 이의신청 등)
- 질문 유형(대상, 선정기준, 금액, 기간, 신청방법, 필요서류, 예외, 제외대상, 담당기관, 처리절차)
- 적용연도
- 지역 범위
- 수치 조건
- 사례 조건(가구, 연령, 소득, 재산, 자동차, 주거, 장애·건강 등)

### 4. 검색 구조 개선

- owning manual을 먼저 식별하고 해당 문서/문서군의 section을 우선합니다.
- 명시 연도 자료가 있으면 다른 연도 문서를 기본 후보에서 제외합니다.
- jurisdiction 우선순위를 적용합니다.
  - 서귀포 질문: Seogwipo → Jeju → National
  - 제주 질문: Jeju → National
  - 국가 질문: National 우선
- authority는 `primary → reference → summary → index` 순으로 유지합니다.
- Semantic Search는 기본 비활성화되며 `WELFARE_SEMANTIC_SEARCH=1`로 명시적으로 켠 경우에만 사용합니다.

### 5. Evidence Slot 및 신뢰도

- 검색 상위 N개를 그대로 전달하지 않고 질문 유형별 Evidence Slot을 우선 채웁니다.
- 각 근거는 `<EVIDENCE id="E1"> ... </EVIDENCE>` 구조로 전달합니다.
- 각 Evidence에 `high / medium / low` 내부 confidence를 기록합니다.
- 선택된 Evidence가 모두 `low`이면 LLM을 호출하지 않고 근거 부족 안내를 반환합니다.
- E2B는 3~5개 근거, 최대 약 9,000자 중심으로 제한합니다.
- E4B는 최대 7개, 약 14,000자까지 사용합니다.

### 6. LLM 호출 구조 단순화

#### E2B

```text
질문
→ Rule Query Planner
→ Retrieval
→ Evidence Selector
→ Gemma 4 E2B Answerer (1회)
→ Deterministic Grounding Validator
→ 최종 답변
```

#### E4B

```text
일반 질문
→ Rule Query Planner
→ Retrieval
→ Evidence Selector
→ Gemma 4 E4B Answerer (1회)
→ Grounding Validator

고난도 질문
→ E4B Answerer
→ E4B Supervisor
→ Grounding Validator
```

Supervisor 추가 조건은 사례형 적격성, 다사업 비교, 복합 조건 등 코드로 판정합니다.

### 7. Grounding Validator 강화

기존 숫자/연도/급여명 검사에 다음을 추가했습니다.

- 사용자 질문에만 존재하는 숫자 제거
- 잘못된 사업명 제거
- `가구원수 ↔ 금액` 관계 검증
- 고위험 부정문/긍정문 반전 검증
- 서로 다른 요청연도 문장 제거
- 중복 문장 제거

### 8. 골든 QA / 자동 평가

- `quality/golden_qa_v1.4.0.json`: 200문항
- `tools/quality_eval_v140.py`: Retrieval 및 선택적 실제 답변 평가
- 측정 항목:
  - Recall@1 / @3 / @5
  - expected section 적중률
  - 금지 주장 포함
  - 기대 숫자 누락
  - 연도 혼입
  - 검색/답변 시간
  - 가능한 경우 프로세스 RSS

## 배포 파일

- E2B: `BokjiTalkAI_Setup_v1.4.0_E2B.exe` — 2,621,571,530바이트
- E4B: `BokjiTalkAI_Setup_v1.4.0_E4B.zip` — 4,883,383,631바이트

E4B ZIP은 Inno Setup 설치 EXE와 분할 데이터 파일 3개(`-1.bin`, `-2.bin`, `-3.bin`)를 함께 포함합니다. ZIP을 한 폴더에 모두 풀고 설치 EXE를 실행해야 합니다.

## 오프라인 원칙

실행 중 OpenAI API, Gemini API, Claude API, 외부 임베딩 API, 외부 reranker, 클라우드 RAG를 사용하지 않습니다. 일반 질의는 로컬 SQLite DB와 로컬 llama.cpp만 사용합니다.

## 검증 상태

최종 배포 후보에서 다음 검증을 완료했습니다.

- 전체 회귀 테스트 **92/92 통과**
- 전체 복지DB 재색인 재현성 테스트 통과(192.34초)
- E2B/E4B 각각 200문항 골든 QA 실측 완료
- Q133의 `보건복지부 고시 제2024-162호`를 정책 적용연도로 잘못 세던 연도 평가기 오탐 수정 및 전체 결과 재채점
- E2B: Recall@1 73.00%, Recall@3 86.00%, Recall@5 91.00%, 금지 주장 3.00%, 연도 혼입 1.50%, 답변 실행 오류 0.00%
- E4B: Recall@1 83.50%, Recall@3 89.00%, Recall@5 90.50%, 금지 주장 0.00%, 연도 혼입 0.00%, 답변 실행 오류 0.00%
- 실제 설치 E2E에서 설치파일을 별도 경로에 설치하고, 반대 모델 부재·39개 원문·21,588개 검색구간·v1.4.0·AI Ready 상태를 확인
- E2B 설치 E2E: 설치 111.429초 / AI Ready 8.709초 / 실제 질문 3.207초 / 제거 성공
- E4B 설치 E2E: 설치 129.264초 / AI Ready 9.717초 / 실제 질문 5.802초 / 제거 성공

세부 결과는 `QUALITY_REPORT_v1.4.0.md`, `QUALITY_REPORT_v1.4.0_E2B.md`, `QUALITY_REPORT_v1.4.0_E4B.md`를 기준으로 합니다.
