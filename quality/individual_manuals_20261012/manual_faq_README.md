# 매뉴얼 FAQ 질문 세트 (2026-10-13)

현재 복지톡 DB에 등록된 원문 변환본 113개를 조사하여 36개 문서에서 FAQ·질의응답 1,173문항을 추출했다. 개별 질문에는 원문 답변, 문서명, 연도, 원문 행 범위, 문서·발췌문 SHA-256, DB 섹션 ID를 넣었다. 원문 질문은 `raw_question`에 보존하고, 평가용 `question`에는 문서명과 FAQ/사업 제목을 붙였다. 종합안내서의 “비용은 얼마인가요?” 같은 질문을 구분하기 위한 문맥이다.

| 파일 | 용도 | 문항 수 |
| --- | --- | ---: |
| `manual_faq.json` | 매뉴얼 FAQ와 원문 정답 후보 | 1,173 |
| `expanded_with_manual_faq.json` | 기존 250 + 민원 200 + 매뉴얼 FAQ | 1,623 |
| `manual_faq_extraction_report.json` | 문서별 수량, 제외·검토 대상과 원문 위치 | — |

기존 `full250.json`, `citizen200.json` 내용과 순서는 그대로 통합했다. 기존 세트와 신규 문항의 정규화된 질문 완전일치, 같은 문서 안의 질문·답변 완전일치를 검사했으며 이번 결과에서 제거한 중복은 0건이다. 표현이 다른 유사 질문이나 다른 연도의 유사 규정을 동일 문항으로 임의 합치지는 않는다. ID는 원문 문서명·행·질문에 따른 해시로 생성한다.

본문의 Q/A, 분리된 질문 번호, 여러 줄 질문, FAQ 안의 번호·제목형 질문과 질의/답변 열이 명확한 HTML 표를 처리했다. 표의 병합셀은 행·열 위치를 복원하되, 번호 없는 질문 조각이 다른 문항에 이어지거나 답변이 여러 열로 나뉘면 표 전체를 검토 대상으로 남긴다. 목차, 설문, OCR 경고, 답변 없는 질문, 질문/답변 경계가 모호한 구간도 제외한다.

검토·제외 목록은 951개 **후보/블록 기록**이다. 표 한 블록에 여러 질문이 있을 수 있고 목차·설문도 포함하므로, 미추출 FAQ 951문항이라는 의미는 아니다. 특히 에너지바우처와 제주가치돌봄 변환본은 두 단 편집으로 질문과 답변 순서가 섞여 자동 짝짓기를 하지 않았다. 통합사례관리 실천가이드는 질문 뒤의 사례 설명과 답변 경계가 모호하여 원본 대조 대상으로 남겼다. 자유로운 제목형 질의, 이미지에만 남은 FAQ, 변환 순서가 섞인 표까지 모두 추출했다는 의미는 아니다.

## 재생성 및 평가

프로젝트 루트에서 실행한다.

```powershell
.\.venv-openkb\Scripts\python.exe -X utf8 tools/build_manual_faq_dataset.py
.\.venv-openkb\Scripts\python.exe tools/eval_individual_manuals.py . quality/individual_manuals_20261012/manual_faq.json quality/individual_manuals_20261012/manual-faq-retrieval
.\.venv-openkb\Scripts\python.exe tools/eval_individual_manuals.py . quality/individual_manuals_20261012/expanded_with_manual_faq.json quality/individual_manuals_20261012/expanded-manual-faq-answers answers
```

생성 도구는 SQLite를 읽기 전용으로 열고 DB의 문서 해시와 변환본 해시가 다르면 중단한다. 신규 문항 1,173개의 발췌문·행 범위·해시를 원문과 전수 대조했고, 1,623개 ID의 유일성, 기존 450문항 보존 및 신규 FAQ 통합을 확인했다. 추출 관련 회귀 테스트 18개, 변경한 4개 Python 파일의 Ruff 검사와 프로그래밍 규칙 검사도 통과했다.

DB SHA-256: `21432e5432751dbbc5a75e70f2508d8a5c761ddadc3a8789017a4140e4884eee`.

`reference_answer`는 원문에서 추출한 **정답 후보**이며, 모든 문항의 의미 검수를 완료한 정답표는 아니다. `review_status`는 `source_verified_pair_semantic_review_pending`이다. 이번 작업에서 모델 답변 재평가는 실행하지 않았다. 다음 평가에서 이 답변과 발췌문을 기준으로 조건·예외·금액·단위·연도를 채점해야 하며, 검색 성공률이나 문자열 일치를 정답률로 보고하면 안 된다. 같은 DB에서 직접 뽑은 질문이므로 기존 민원 200문항과 매뉴얼 FAQ 성적은 별도로 제시해야 한다.

이 작업은 로컬 평가 질문 세트 추가다. 서비스 DB의 공식 129 FAQ 788건, 배포 파일과 GitLab 릴리스는 변경하지 않았다.
