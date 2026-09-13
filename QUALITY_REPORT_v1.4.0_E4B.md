# QUALITY REPORT v1.4.0

- 배포 변형: **E4B**
- 모델: `gemma4-e4b.gguf`
- 평가 문항: **200개**
- Retrieval Recall@1: **83.50%**
- Retrieval Recall@3: **89.00%**
- Retrieval Recall@5: **90.50%**
- 문서+section 적중률@5: **89.00%**
- 평균 검색시간: **314.8 ms**
- 평균 답변시간: **20498.0 ms**
- 금지 주장 포함률: **0.00%**
- 기대 숫자 누락률: **4.00%**
- 연도 혼입률: **0.00%**
- 답변 실행 오류율: **0.00%**
- 최대 관측 RSS: **11532.4 MB**

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

- 상세 CSV: `C:\Users\USER\Downloads\seoguipowelfare-v1.3.4\seoguipowelfare-v1.3.4\quality\results_v1.4.0_E4B.csv`

> 답변 지표는 `--answers`로 실제 로컬 모델까지 실행한 경우에만 측정합니다. Retrieval-only 실행에서는 답변 관련 항목을 `미측정`으로 남깁니다.

## 실제 런타임 측정

- GPU offload layers: **99**
- 실제 로딩 모델: `gemma4-e4b.gguf`
- 체크포인트: `C:\Users\USER\Downloads\seoguipowelfare-v1.3.4\seoguipowelfare-v1.3.4\quality\checkpoint_v1.4.0_E4B.jsonl`

## 평가기 재채점 보정

- Q133의 `보건복지부 고시 제2024-162호`는 2026년 지침이 인용한 **고시 식별자**이며 2024년 지원기준을 적용한 것이 아닙니다.
- 기존 200문항 실측 답변·응답시간은 그대로 보존하고, 개선된 평가 규칙으로 파생 지표만 다시 계산했습니다.
- 재채점 후 E4B 연도 혼입 판정은 **0/200 (0.00%)**입니다.
