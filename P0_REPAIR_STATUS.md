# v1.4.0.Beta — P0 복구 수정 내역

작성일: 2026-09-20

**현재 상태: P0 복구 검증 통과. 183/183 회귀시험 통과, 저장된 실제 초안 38건 재생 완료. A1_FIX 후보이며 A1_READY/배포 승인 아님.**

## 기준과 보존

2026-09-20 Jev·LAYA 종합 개선방안, 실제 E2B 비교평가(계획 48건 중 38건), 그에 따른 Beta 개선계획의 첫 개발 묶음을 적용했다. 이전 146개 pytest 결과는 현재 패치 이전의 결과다.

수정은 `C:\Users\USER\Documents\Codex\seoguipowelfare-v1.4.0.Beta`에만 적용했다. 원본 v1.4.0·기존 모델·기존 DB·`quality/real_ab/20260920T021551273093Z`의 측정 스냅샷과 기록에는 쓰기 명령을 수행하지 않았다. 이번 패치 이후 전체 원본 해시 확인은 아래 검증 실행 전이므로 아직 없다.

## 반영 사항

### 1. 근거 계약

`welfare_evidence.py`에 `EvidenceContext`(기존 문자열 호출과 호환)와 버전 표시 메타데이터 직렬화를 추가했다. 검색기가 만든 불변 메타데이터·본문 객체를 최종 검증에 직접 전달한다. 숫자 포함 키 `source_sha256`, 한글·대괄호·따옴표·역슬래시·개행 값을 보존하고 메타데이터 값을 한 물리적 줄로 안전하게 인코딩한다.

기존 측정자료를 재생하기 위해 legacy multiline `references`를 제한적으로 읽는다. 본문을 다시 훑어 메타데이터를 찾아내지 않는다. 중복 키/ID·깨진 구조·미지원 인코딩은 수용하지 않는다. 원문에 없는 페이지·적용기간을 생성하지 않는다.

`welfare_search/context.py`는 이제 근거 객체로 결과를 구성한다. 표 단위·머리글·각주가 떨어지지 않도록 구간 본문을 온전히 유지하되 기존 전체 문자 예산은 그대로 적용한다. 큰 구간이 예산에 들어가지 않으면 부분 표를 정답으로 취급하지 않고 해당 구간을 넣지 않는다. 이 정책의 검색 누락·속도 영향은 새 추론에서 별도 검증해야 하며 완전한 슬롯 충족을 보증하지 않는다.

### 2. 표 수치 관계

새 `welfare_table_facts.py`는 단위가 명시된 직사각형 Markdown 가구원수 표를 읽는다. 가구원수·원 단위로 정규화한 값·원래 단위·주기·지표·표 해시·행열·본문 상대 위치·이어진 각주를 같이 기록한다. 가로형과 단순 세로형을 지원한다.

HTML 병합 셀, 다층 머리글, 수식/범위 값, 불명확한 단위 등은 아직 구조화하지 않는다. 본문 상대 위치를 PDF 페이지라고 표시하지 않는다. 추가 정본·사업 소속·세부 적용연도 검수와 복잡한 관계 검증은 후속 범위다.

`welfare_grounding.py`에 표 금액·가구원수 관계를 연결하고 Markdown 강조표시를 제거한 수치 비교를 적용했다. 근거 본문과 메타데이터 숫자를 분리하고 참고문헌 제목·파일명·해시를 금액의 근거로 쓰지 않는다. 명시된 인용 ID와 개별 구간 검증을 유지하며, 질문에 있는 금액을 원문 근거로 더하지 않는다.

### 3. 답변 완결성

새 `welfare_answer_quality.py`는 `COMPLETE_CANDIDATE / PARTIAL / ABSTAIN`을 구조적 상태로 제공한다. `COMPLETE_CANDIDATE`도 사실 정확성의 증명이 아니며 correctness는 `UNREVIEWED`다. 금액 질문의 금액 누락, 출처만 남음, 답변 불가 문구, 제거된 주장 및 출력 상한을 별도로 기록한다. 부분 답변/보류 안내를 최종 결과에 연결했다.

`welfare_telemetry.py`는 앱 실행 완료와 `answer_quality`를 구분한다. `welfare_llm.py`에서 실제 `finish_reason`/길이 상한을 기록한다. 기본 진단에 질문·답변 원문을 추가하지 않았다.

## 시험 및 재생

- `tests/test_beta_p0_repair.py`: 실제 메타데이터 왕복, 구조 주입/중복 거부, 표 단위·가구원수·주기·인용 불일치, 핵심 답변 누락, 실제 Q057 초안 재생 회귀시험.
- `tools/validate_p0_repair.py`: 전체 pytest + 저장된 38개 실제 초안 재생 + 원본/기존 기록 해시 비교. 새 모델 추론이나 다운로드는 하지 않는다.
- 결과 위치: 실행 후 `quality/p0_repair/<새 UTC 실행ID>/`. 과거 로그를 덮어쓰지 않는다. 각 재생 후 체크포인트를 저장하며 `latest.json`은 이 검증 경로 전용이다.

실행 명령(cmd):

```cmd
cd /d C:\Users\USER\Documents\Codex\seoguipowelfare-v1.4.0.Beta
C:\Users\USER\Documents\Codex\seoguipowelfare\deploy-current\.venv-openkb\Scripts\python.exe -X utf8 -B tools\validate_p0_repair.py
```

2026-09-20 첫 검증 실행 결과는 `quality/p0_repair/20260920T030022335731Z/`에 보존했다. 지정한 시스템 Python에 pytest와 PyYAML이 없어 단위시험·초안 재생을 수행하지 못했다. 구문 검사 통과, 원본 검사 대상 156개 파일과 records.jsonl의 전후 해시 일치는 확인했다. 종료코드 1이며 통과 결과가 아니다.

실행 파일을 앞선 실제 E2B 비교에 사용한 기존 `.venv-openkb/Scripts/python.exe`로 바꾼 정확한 명령 승인을 요청했다. 해당 환경의 pytest 및 yaml 패키지 파일 존재를 확인했으나 이번 재실행의 import·시험 결과는 아직 없다. 패키지 설치·다운로드와 복지톡 본체 코드 변경은 하지 않았다. 검증기는 `sys.executable`을 사용하므로 pytest도 같은 가상환경으로 실행한다.

최종 통과 실행은 `quality/p0_repair/20260920T033710147949Z/`에 보존했다. pytest는 **183 passed / 0 failed / 0 errors / 0 skipped**이며 기존 라이브러리 경고 2개만 남았다. 저장된 실제 초안 38건을 모두 재생했고, 금액 검증 대상 18건 중 골드 금액이 실제 초안에 존재한 15건은 **기존 최종답 0/15 → 수정 검증기 재생 15/15 보존**으로 개선됐다. 원본 156개 파일과 fixture의 전후 해시도 일치한다. 단, `whole_answer_correctness=UNREVIEWED`, `new_inference_speedup=NOT_MEASURED`이므로 새 추론 정확도·속도 성과로 해석하지 않는다.

## 다음 단계로 넘기지 않은 항목

선택적 판단은 OFF. LAYA 설치·가중치 다운로드·동일 Gemma 추가 판단·외부 API 호출을 추가하지 않았다. 사업 소속/제외조건 검색, 요청/제외 연도 구분, 질문 유형별 출력 정책, 재개 가능한 실제 A/B 실행기, 240문항 검수, 8GB/16GB 시험, EXE·설치·UI·보안 인수는 완료되지 않았다.

P0 회귀와 실제 초안 재생은 통과했다. 다음 단계는 같은 E2B·공통 DB·동일 질문으로 새 추론을 실행해 A1_FIX의 실제 품질·지연을 재평가하는 것이다. 이전 실패 Beta는 A1_PRE, 이번 수정은 A1_FIX이며 실제 재추론과 후속 검색/시점 개선 전에는 A1_READY라고 부르지 않는다.
