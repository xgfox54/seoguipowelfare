# v1.4.0.Beta — 최종 판정 (2026-09-26)

## 1. 최종 판정: A1_READY

최종 코드로 돌린 잠금 200문항 E2B 실행 `quality/final_locked200/final_r3_20260925T232718Z`가 작업지시서 16장의 최소 조건 14개를 모두 충족합니다. 2026-09-25 오전 판정(A1_READY_BLOCKED, `A1_READY_FINAL_20260925.md`)을 막던 두 결함은 이 실행에서 재현되지 않았습니다.

**A1_READY는 개발단계 후보 판정이며 production ready가 아닙니다.** 설치본·실기 인수 항목은 8장에 따로 남아 있습니다.

| 최소 조건 | 결과 | 근거 |
|---|---|---|
| 200/200 실행 완료 | 충족 | FINAL_STATUS COMPLETED, 200/200 |
| 추론 오류 0 | 충족 | answer_error 0 |
| expected number 골드 핵심 문항 | 충족 | 8/8 (Q057~Q062, Q175, Q176) |
| wrong premise 핵심 문항 | 충족 | Q175 1,994,600원, Q176 783,000원 제시, 200만원·80만원 채택 없음, 잘못된 전제 채택 0 |
| Q063 회귀 없음 | 충족 | 기초연금 신청 절차, 부분 → 완결 |
| Q145 연도 혼입 없음 | 충족 | wrong_years 없음, 2026년 선정기준만 제시 |
| Q188 지역업무 혼합 없음 | 충족 | 식사지원 외 하위 서비스 혼입 신호 없음 |
| Q056 타사업 수치 혼입 없음 | 충족 | 현황 자료 안내만, 552,000원·긴급복지 없음 |
| 중대한 program mix 없음 | 충족 | 신호 7건 = 02번 공통업무 안내(기초생활 계열 공동 소유 문서) 6건 + Q069의 12번 읍면동복지매뉴얼 1건. 사람 검수 목록에 포함 |
| 출력 잘림이 배포 차단 수준 아님 | 충족(주의) | 17/200, 잘린 답은 "부분" 판정과 안내가 붙음. final_r2와 같은 수 |
| 전체 pytest 통과 | 충족 | 296 passed, 실패·오류·건너뜀 0 (`quality/final_pytest/20260925T221507Z`) |
| P0 replay 통과 | 충족 | passed, 금액 골드 15/15 (`quality/p0_repair/20260925T221517660238Z`) |
| 원본 v1.4.0 해시 불변 | 충족 | 156개 파일 불일치 0 |
| decision_mode OFF | 충족 | preflight decision_mode OFF, external_fallback false, raw_query_logging false, max_retrieval_retries 1 |

## 2. 수정한 문제 (A1_READY_BLOCKED 이후)

| 문제 | 원인 | 수정 파일 | 회귀 방지 테스트 | 결과 |
|---|---|---|---|---|
| B1 제외 사업 혼입(Q171~Q174) | "○○ 조건을 섞지 마"의 제외 사업 매뉴얼이 근거로 선택됨 | `welfare_search/query.py`, `welfare_search/context.py` | `tests/test_v140_beta_improvements.py` | final_r2·r3에서 재현 없음 |
| B2 연도 제외 문형 오해석(Q145~Q159) | "2025년 기준과 섞지 말고"가 요청 사업을 제외 | `welfare_search/query.py`, `welfare_search/search.py` | 같은 파일 | 연도 혼동 R@5 26.7% → 93.3% |
| 근거 지침 형식 회귀 | 모델용 근거에서 파일명을 빼면서 태그·ID만 나열 | `welfare_grounding.py`, `welfare_agent.py` | 같은 파일 | final_r3에서 태그 0 |
| 단일 금액 질문 보류(E4B, Q057~Q062) | 단일 금액 전용 경로에서 E4B가 표 값을 내지 못함 | `welfare_answer_format.py`, `welfare_assistant.py` | `tests/test_single_amount_table_fallback.py` (14건) | E4B 재실행 금액 골드 2/8 → 8/8 |
| 근거 묶음 누락(Q027·Q028·Q084·Q103·Q119) | 잘린 서비스명이 바우처 보조검색을 켬, 기준어 없는 일반 단어 보조검색이 앞자리를 차지 | `welfare_search/context.py` | `tests/test_final_retrieval_fixes.py` (5건) | 기대 문서 포함 178 → 183, 새 누락 0 |
| 보고서 도구 오집계 | 근거 지침의 파일명 줄을 수치 주장으로 셈 | `tools/final_locked200_report.py` | — (집계 도구) | 근거 없는 수치 72 → 0, 제외 줄 수 별도 기록 |

세부 설명은 `IMPROVEMENTS_v1.4.0.Beta_20260925.md` 3·5장입니다.

## 3. 전체 테스트

| 시험 | 결과 |
|---|---|
| pytest | 296 passed, 경고 2(기존 라이브러리 deprecation) |
| P0 replay | passed, 저장 초안 38건 재생(금액 평가 18건 중 초안에 골드가 있던 15건 모두 보존), 원본·fixture 불변 |
| 표적 E2B | `quality/final_targeted/targeted_r3_sourceguide` 59문항(근거 지침 수정) |
| 표적 E4B | `quality/final_targeted_e4b/targeted_e4b_r1_finalfixes` 19문항, 완결 15 / 부분 4 / 보류 0 |
| 잠금 200 E2B | `final_r3` 200/200, 아래 4장 |
| 잠금 200 E4B | `quality/final_locked200_e4b/final_e4b_r1_20260925T095920Z` 200/200 (수정 전 코드, 참고) |

## 4. 200문항 결과 (final_r3)

전체: R@1 92.0%, R@3 96.5%, R@5 98.0%, 섹션 적중@5 97.0%. 자동 판정 완결 132 / 부분 61 / 보류 7. 금지 주장·연도 혼입·잘못된 전제 채택·잘못된 Evidence ID·근거 없는 수치 0. 출력 잘림 17.

| 유형 | 문항 | R@5 | 완결 / 부분 / 보류 |
|---|---:|---:|---|
| 단순 | 30 | 100% | 29 / 1 / 0 |
| 수치 | 32 | 100% | 17 / 14 / 1 |
| 절차 | 22 | 100% | 19 / 3 / 0 |
| 예외 | 20 | 100% | 16 / 4 / 0 |
| 사례 | 40 | 95.0% | 22 / 18 / 0 |
| 연도 혼동 | 15 | 93.3% | 9 / 3 / 3 |
| 사업 혼합 | 15 | 93.3% | 7 / 7 / 1 |
| 틀린 전제 | 10 | 100% | 7 / 3 / 0 |
| 지역 | 10 | 100% | 5 / 3 / 2 |
| 표 | 6 | 100% | 1 / 5 / 0 |

자동 판정은 형식 판정입니다. 정답 여부는 사람 검수 대상입니다(`quality/final_locked200/final_r3_20260925T232718Z/HUMAN_REVIEW_final_r3.md`).

## 5. 실패·주의 문항

- 보고서 실패 목록 76건: `quality/final_locked200/final_r3_20260925T232718Z/report/FAILURE_REVIEW.md`.
- 출력 잘림 17건: Q068·Q079·Q102·Q110·Q127·Q128·Q130·Q147·Q169·Q172·Q179·Q185·Q192·Q193·Q197·Q198·Q199.
- 원문 확인 불가로만 답했는데 "완결"로 판정된 문항 9건, 확인 불가만 답한 문항 전체 16건.
- 근거에 기대 문서가 없는 문항 15건: 같은 사업을 다루는 다른 매뉴얼 10건(노인맞춤돌봄 등), 다른 근거 5건(Q030·Q051·Q120·Q137·Q138).
- Q176은 첫 문장이 "확인되지 않습니다"인데 본문에서 783,000원을 제시하는 모순이 있습니다.

## 6. 성능 (이 검증 PC: AMD Ryzen 5 7530U, 내장 Radeon, 메모리 약 14GB, llama.cpp b10686 Vulkan)

| 모델 | 평균 | p50 | p95 | 최대 | 최대 표본 메모리 RSS / private |
|---|---:|---:|---:|---:|---|
| E2B (final_r3) | 88.8초 | 93.2초 | 128.6초 | 143.4초 | 5,542 / 11,554MB |
| E4B (final_e4b_r1) | 218.0초 | 230.3초 | 307.6초 | 346.1초 | 6,216 / 14,195MB |

8GB·16GB 업무용 PC에서는 측정하지 않았습니다.

## 7. 불변성

| 항목 | 값 |
|---|---|
| 원본 v1.4.0 | 156개 파일 해시 일치, 불일치 0 |
| 소스 스냅샷 (final_r3, E4B 19문항 재실행과 동일) | `059569201ed99d7bc811f79a3f9cf66c094fd4d035099cbf5fe094d6ef2bfefe` |
| 소스 코드 해시 | `7991a7690b37d59d8d0e6cd37155bab5524c428b575d0374afa4e1c521006464` |
| E2B 모델 gemma4-e2b-it-qat.gguf | `e531007218dfab990486a5de7676a6932d6ea8dea233d1f698d7c21cf8a16889` |
| E4B 모델 gemma4-e4b.gguf | `85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87` |
| 검색 DB welfare.db | `695f7ae17be32f8abc6b4503e92a23528c39f1611aa497b33bb7847ede5c1d02` |
| llama-server (b10686) | `79f9eee912d76bdc7062c89813cd2fc4452a90bbfcae591bfaf4c88ecb3ea735` |
| 사업 사전 program_dictionary.json | `71c890eda860722af368bedb48181b863bf6b0b51d98b85e71989c85e389c22d` |
| 평가셋 golden_qa_v1.4.0.json | `a6dc8748f522a956476c02e751d99727f477d1dd54f707cbf30b0c44836b55ca` |
| 평가기 묶음 | `70e54871ef99c916149891a5cd3a819c9206d82b90074776a397b2d11db8218f` |

## 8. 남은 배포 게이트

| 게이트 | 상태 |
|---|---|
| 사람 검수(정답 여부) | 검수표 작성(64문항, `HUMAN_REVIEW_final_r3.xlsx`), 검수 미수행 |
| 최신 Beta EXE 빌드 | 완료: E2B·E4B setup.exe(Inno Setup 6.7.3), SHA-256 목록 `dist/SHA256SUMS_v1.4.0.Beta_20260926.txt` (`PACKAGING_REPORT_v1.4.0.Beta.md`). 코드 서명 없음 |
| 설치/제거 E2E | 이 PC(현재 사용자)에서 E2B·E4B 설치 → 실행 → 제거 통과. 깨끗한 PC 설치는 미수행 |
| 8GB 업무용 PC 실기 인수 | 미수행 |
| 16GB PC 실기 인수 | 미수행 |
| UI/UX 인수 | 첫 화면 표시·종료 버튼만 확인, 인수 미수행. 매뉴얼 수 문구는 실제 수(39개)로 수정 |
| 오프라인 네트워크 검증 | 부분: 127.0.0.1에서만 대기, 질문 처리 중 외부 연결 0건. 인터넷 차단 상태 시험 미수행 |
| Host/Origin/API 보안 검증 | 결함 2건(교차 출처 종료, Host 미검사) 수정 후 설치본에서 재시험 통과. 외부 전문 점검은 미수행 |
| 최종 배포파일 SHA 고정 | 미수행 |
| 롤백 패키지 검증 | 미수행 |
| E4B 최종 코드 전체 200문항 | 영향 19문항만 재실행. E4B를 정식 제공하려면 필요 |

## 9. 판정 후 변경 (2026-09-26 오후, 웹 계층 보안 수정)

설치본 점검에서 찾은 결함 두 가지를 판정 후에 고쳤습니다. 외부 웹페이지가 종료 API로 앱을 끌 수 있었고, Host 헤더를 검사하지 않았습니다. 수정은 `welfare_web.py`와 `web/`(app.js, index.html, showcase.html)에만 있고, final_r3 소스 스냅샷과 비교하면 나머지 41개 파일(검색·답변·검증 코드 포함)은 같습니다. 따라서 4장의 200문항 결과는 수정 후 코드에도 그대로 해당합니다.

- 전체 pytest 302 passed(`quality/final_pytest/20260926T072020Z`, 새 테스트 `tests/test_web_local_guard.py` 6건 포함).
- P0 replay 통과(`quality/p0_repair/20260926T072453313566Z`, 테스트 302, 금액 골드 15/15, 원본 불변).
- 설치본 재시험: 외부 Host 400, 외부 출처 요청 403, text/plain 종료 요청 422, 같은 출처 JSON 종료만 동작(`PACKAGING_REPORT_v1.4.0.Beta.md` 2차).

## 이력

| 단계 | 상태 |
|---|---|
| A1_FIX (2026-09-20) | `A1_FIX_STATUS_20260920.md` |
| A1_READY 후보 (2026-09-20) | `A1_READY_CANDIDATE_20260920.md` |
| 56/200 부분 실행 (2026-09-21) | `quality/locked200_a1ready_postnumeric`, 참고 보존·미합산 |
| 최종 검증 1차 (2026-09-25 오전) | A1_READY_BLOCKED, `A1_READY_FINAL_20260925.md` |
| 개선 적용·최종 코드 검증 (2026-09-26) | **A1_READY**, 본 문서 |
