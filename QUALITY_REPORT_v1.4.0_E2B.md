# QUALITY REPORT v1.4.0

- 배포 변형: **E2B**
- 모델: `gemma4-e2b-it-qat.gguf`
- 평가 문항: **200개**
- Retrieval Recall@1: **73.00%**
- Retrieval Recall@3: **86.00%**
- Retrieval Recall@5: **91.00%**
- 문서+section 적중률@5: **89.00%**
- 평균 검색시간: **252.8 ms**
- 평균 답변시간: **9196.1 ms**
- 금지 주장 포함률: **3.00%**
- 기대 숫자 누락률: **4.00%**
- 연도 혼입률: **1.50%**
- 답변 실행 오류율: **0.00%**
- 최대 관측 RSS: **5642.2 MB**

## 문항 구성

- case: 40
- exception: 20
- local: 10
- numeric: 32
- procedure: 22
- program_mix: 15
- simple: 30
- table: 6
- wrong_premise: 10
- year_confusion: 15

## 산출 파일

- 상세 CSV: `C:\Users\USER\Downloads\seoguipowelfare-v1.3.4\seoguipowelfare-v1.3.4\quality\results_v1.4.0_E2B.csv`

> 답변 지표는 `--answers`로 실제 로컬 모델까지 실행한 경우에만 측정합니다. Retrieval-only 실행에서는 답변 관련 항목을 `미측정`으로 남깁니다.

## 평가기 재채점 보정

- 기존 200문항 실측 답변·응답시간은 그대로 보존하고, 개선된 평가 규칙으로 파생 지표만 다시 계산했습니다.
- 고시·공고 번호에 포함된 연도와 부정·정정 문맥의 금지 표현을 실제 오류로 세지 않도록 보정했습니다.
- 재채점 후 실제 연도 혼입 판정은 **3/200 (1.50%)**입니다.
