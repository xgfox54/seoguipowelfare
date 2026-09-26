# v1.5.0 패키징·설치 시험 보고

작성일: 2026-09-26

v1.4.0.Beta에서 A1_READY 판정을 받은 코드를 정식판 v1.5.0으로 전환하고, E2B·E4B 설치 파일을 만들어 이 PC에서 업그레이드 설치, 새 설치, 실행, 제거를 시험했습니다. 두 설치 파일 모두 설치·실행·답변·보안 점검을 통과했습니다. 제거는 E4B에서 깨끗하게 끝났고, E2B는 창을 연 채 제거를 돌린 시험 절차 때문에 사용 중인 파일이 남았습니다(아래 "제거 시험" 참고).

## 1. 정식판 전환 내용

Beta 전용 설정을 걷어내고 v1.4.0 정식판과 같은 설치 ID·설치 폴더·포트로 되돌렸습니다. 원본 v1.4.0과 비교하면 `installer.iss`는 버전, 파일 버전 정보, 이전 파일 정리(`[InstallDelete]`)만 다릅니다.

| 항목 | v1.4.0.Beta | v1.5.0 |
|---|---|---|
| 버전 | `1.4.0.Beta` (Windows 1.4.0.1, 시험판 표시) | `1.5.0` (Windows 1.5.0.0) |
| 설치 ID·폴더 (E2B) | `BokjiTalkAI_Beta_E2B` | `{7E4B2C1A-9D3F-4A6B-8C5E-2F1D0B9A7E63}`, `%LOCALAPPDATA%\BokjiTalkAI` (v1.4.0과 같음) |
| 설치 ID·폴더 (E4B) | `BokjiTalkAI_Beta_E4B` | `BokjiTalkAI_E4B`, `%LOCALAPPDATA%\BokjiTalkAI_E4B` (v1.4.0과 같음) |
| 포트 (웹 / 모델 서버) | 8766 / 18081 | 8765 / 18080 (v1.4.0과 같음) |
| 창 제목·화면 문구 | Beta 표시 | 정식판 제목, "답변 처리 내역" |
| 업그레이드 정리 | 없음 | 설치할 때 이전 실행 파일(`복지업무비서_v*.exe`)과 `_internal` 폴더를 먼저 삭제 |
| 판정 정책 버전 | Beta | `1.5.0-gate-1` (기본값 유지: `decision_mode` OFF, `external_fallback` false, `raw_query_logging` false, `max_retrieval_retries` 1) |

테스트는 버전과 포트 기대값만 바꿨고 확인 항목은 줄이지 않았습니다(`test_release_version_and_default_model_port`, `test_welfare_web.py`, `test_web_local_guard.py`). 검색·답변·검증 코드는 A1_READY 판정 코드와 같습니다.

- 전체 pytest: **302 passed** (`quality/final_pytest/20260926T081018Z_v150`)
- P0 저장 초안 재생: 통과, 금액 골드 15/15, 원본 v1.4.0 불변 (`quality/p0_repair/20260926T081617875726Z`)

## 2. 빌드

- 환경: `.venv-package`(Python 3.12, PyInstaller 6.16.0), Inno Setup 6.7.3(`%LOCALAPPDATA%\Programs\Inno Setup 6`).
- 명령: `build-exe.ps1 -ModelVariant E2B`, `-ModelVariant E4B`. 두 빌드 모두 종료 코드 0. 설치 파일 압축 시간은 E2B 180.3초, E4B 444.7초.
- 경고: `webview.platforms.android`, `pycparser.lextab/yacctab`, `tzdata` 미수집 경고만 있습니다. Beta 빌드와 같고 실행에 영향이 없습니다.

| 실행 폴더 (dist) | 파일 수 | 크기(바이트) | 실행 파일 SHA-256 |
|---|---:|---:|---|
| `BokjiTalkAI_v1.5.0_E2B` | 232 | 3,047,176,857 | `ad8bc35e04f91a46e912534138b65450df83e0967956351a2e6ff1261b56ea48` |
| `BokjiTalkAI_v1.5.0_E4B` | 232 | 5,403,977,465 | `e9ddf4dbb92005a9c6a083a72df8fc69f3baeac77806ebfd6ea922da13731f19` |

번들 자산은 검증에 쓴 파일과 해시가 같습니다.

| 자산 | SHA-256 |
|---|---|
| 검색 DB `wiki/kb-v120/welfare.db` (286,445,568바이트) | `695f7ae17be32f8abc6b4503e92a23528c39f1611aa497b33bb7847ede5c1d02` |
| 사업 사전 `resources/program_dictionary.json` | `71c890eda860722af368bedb48181b863bf6b0b51d98b85e71989c85e389c22d` |
| llama-server (b10686 Vulkan) | `79f9eee912d76bdc7062c89813cd2fc4452a90bbfcae591bfaf4c88ecb3ea735` |
| E2B 모델 `gemma4-e2b-it-qat.gguf` | `e531007218dfab990486a5de7676a6932d6ea8dea233d1f698d7c21cf8a16889` |
| E4B 모델 `gemma4-e4b.gguf` | `85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87` |

## 3. 배포 파일

체크섬 파일: `dist/SHA256SUMS_v1.5.0.txt` (사본 `quality/packaging_v150_20260926/`).

| 파일 | 크기(바이트) | SHA-256 |
|---|---:|---|
| `BokjiTalkAI_Setup_v1.5.0_E2B.exe` | 2,620,334,863 | `d387bac2a7254468fd88cd63d9a57d8044cc8f57b06155e01ae46883b8188a36` |
| `BokjiTalkAI_Setup_v1.5.0_E4B.zip` (아래 4개 묶음) | 4,882,146,045 | `6538c6d3539f9d483e15f3b2d4042dd7718ea8ddf9e684e0150906c2835f2270` |
| `BokjiTalkAI_Setup_v1.5.0_E4B.exe` | 2,410,620 | `5e816e23c7ac0a863a4a60b5184e33eec802dbd7fee74c88bfa31937fe9c86f0` |
| `BokjiTalkAI_Setup_v1.5.0_E4B-1.bin` | 1,897,588,992 | `a5a27d8137c8c268434f1a0bfc8553b4b3c10a2856807cce6cf342ee456fd62b` |
| `BokjiTalkAI_Setup_v1.5.0_E4B-2.bin` | 1,900,000,000 | `bb42ddd440623b81b7e3ebccc55dbaa6830644e46d1aea79381e61014ab08f0d` |
| `BokjiTalkAI_Setup_v1.5.0_E4B-3.bin` | 1,082,537,216 | `f82dc10c6201afa801c8256e7d8a8ec3d0d15d1aa098b84c96c08045b9d8be02` |

E4B는 설치 EXE와 분할 파일 3개가 같은 폴더에 있어야 설치됩니다. ZIP을 풀면 네 파일이 한 폴더에 나오며, 이 PC에서 푼 파일의 크기가 위 표와 같았습니다.

## 4. 설치 시험 (이 PC, 현재 사용자, 무인 설치 `/VERYSILENT`)

### 4.1 E2B: v1.4.0 → v1.5.0 업그레이드

원본 v1.4.0 소스를 그대로 빌드한 설치 파일(`D:\BokjiTalk_upgrade_test\v1.4.0_src\dist\BokjiTalkAI_Setup_v1.4.0_E2B.exe`)로 v1.4.0을 설치해 실행(포트 8765, 버전 1.4.0, AI 준비 완료)하고 종료한 뒤, 그 위에 v1.5.0 E2B를 설치했습니다.

| 확인 항목 | 결과 |
|---|---|
| 설치 | 성공(Inno Setup 로그 "Installation process succeeded"), 약 157초. 같은 설치 ID로 인식해 기존 제거 기록에 이어 씀 |
| 이전 실행 파일 | `복지업무비서_v1.4.0_E2B.exe` 삭제, `복지업무비서_v1.5.0_E2B.exe`만 남음 |
| `_internal` | 새로 설치됨(빌드 이전 날짜의 파일 0개), VERSION 1.5.0 |
| 제거 목록 | 1건, "복지톡AI 복지업무비서 v1.5.0 (E2B)", 버전 1.5.0 |
| 바로가기 | 바탕화면·시작 메뉴 모두 v1.5.0 실행 파일을 가리킴 |
| 검색 DB | SHA-256 `695f7ae1…1d02` |
| 준비 시간 | 9.6초(버전 1.5.0, E2B 모델, 매뉴얼 39개, 상태 "정상") |
| 단일 금액 "2026년 긴급복지 생계지원 4인 가구 금액" | 55.6초, 1,994,600원 |
| 연도 불일치 "2025년 긴급복지 소득기준" | 0.2초, "로컬 DB에는 2025년 긴급복지 자료가 없습니다" 안내(모델 호출 없음) |

### 4.2 E4B: 새 설치 (ZIP에서 푼 분할 설치 파일)

| 확인 항목 | 결과 |
|---|---|
| ZIP 풀기 | 24초, 4개 파일 크기 일치 |
| 설치 | 종료 코드 0, 169초. `%LOCALAPPDATA%\BokjiTalkAI_E4B` |
| 설치본 | 실행 파일 `복지업무비서_v1.5.0_E4B.exe`, VERSION 1.5.0, 모델 `gemma4-e4b.gguf` 4,977,171,584바이트, DB 해시 일치 |
| 제거 목록·바로가기 | "복지톡AI 복지업무비서 E4B v1.5.0 (E4B)"(v1.4.0과 같은 이름 규칙), 바탕화면·시작 메뉴 바로가기 |
| 준비 시간 | 19.3초(버전 1.5.0, E4B 모델, 매뉴얼 39개) |
| 단일 금액(4인) | 183.1초, 월 1,994,600원 |
| 연도 불일치 | 0.8초, 결정론적 안내 |
| 로그의 질문 원문 | 0건 |

### 4.3 로컬 웹 보안 점검 (설치본, E2B·E4B 같음)

| 요청 | 응답 |
|---|---|
| Host `evil.example:8765`로 상태 조회 | 400 |
| Origin `http://evil.example`로 질문 | 403 |
| Origin `http://evil.example`, text/plain 종료 | 403, 앱 유지 |
| Origin 없는 text/plain 종료 | 422, 앱 유지 |
| `Sec-Fetch-Site: cross-site` JSON 종료 | 403, 앱 유지 |
| 같은 출처(`http://127.0.0.1:8765`) JSON 종료 | 200, 웹서버·llama-server 종료 |

### 4.4 제거 시험

| 설치본 | 절차 | 결과 |
|---|---|---|
| E4B | 창 닫기 → 제거 | 창을 닫자 앱·llama-server 프로세스 0개. 제거 종료 코드 0, 13초. 설치 폴더·제거 목록·바탕화면 바로가기·시작 메뉴 폴더 모두 삭제 |
| E2B | 창을 연 채 제거(시험 절차 누락) | 제거 목록·바로가기·시작 메뉴 폴더·모델·런타임은 삭제. 실행 중이던 실행 파일과 `_internal`, `logs`(36개 파일, 319,662,611바이트)가 남음 |

E2B에서 파일이 남은 원인은 시험 절차입니다. 점검 스크립트가 보낸 종료 API는 웹서버와 llama-server만 끄고 프로그램 창은 그대로 둡니다. 화면의 "프로그램 종료" 버튼은 종료 API를 부른 뒤 창까지 닫고(`web/app.js`의 `close_app`), 창을 닫으면 프로세스가 끝나는 것을 확인했습니다. 런처 동작은 원본 v1.4.0과 같습니다. 창을 먼저 닫고 제거한 E4B는 깨끗하게 지워졌습니다.

남은 E2B 폴더(`%LOCALAPPDATA%\BokjiTalkAI`)는 이 PC에만 있고, 제거 목록과 바로가기가 없습니다. 셸에서 폴더를 지우는 명령은 작업 환경의 실행 정책에 막혀 남겨 두었습니다. 직접 지워도 되고, v1.5.0을 다시 설치하면 `[InstallDelete]`가 이전 실행 파일과 `_internal`을 정리합니다.

사용자 안내: 업그레이드나 제거 전에는 "프로그램 종료" 버튼이나 창 닫기로 프로그램을 끄세요. 설치할 때는 Inno Setup이 사용 중인 파일을 가진 프로그램을 닫지만(`CloseApplications=yes`), 제거 프로그램은 실행 중인 프로그램을 닫지 않습니다.

기록: `quality/packaging_v150_20260926/` (빌드 로그, 설치 로그, 점검 결과 JSON, 제거 결과, 시험 스크립트).

## 5. 남은 항목

- 코드 서명: 설치 파일이 서명되지 않아 다른 PC에서 SmartScreen 경고가 나올 수 있습니다.
- 개발 도구가 없는 깨끗한 PC 설치, 8GB·16GB 업무용 PC 실기 인수, 인터넷 차단 상태 시험.
- E4B v1.4.0 → v1.5.0 업그레이드는 설치 ID가 같지만 이 PC에서 시험하지 않았습니다.
- 사람 검수: `quality/final_locked200/final_r3_20260925T232718Z/HUMAN_REVIEW_final_r3.xlsx` 64문항.

## 6. 이 PC에 남긴 시험 자료

- `D:\BokjiTalk_build_archive\v1.4.0.Beta_dist_20260926`: Beta 설치 파일 보관본.
- `D:\BokjiTalk_upgrade_test\v1.4.0_src`: 업그레이드 시험용 원본 v1.4.0 복사본과 그 설치 파일.
- `D:\BokjiTalk_upgrade_test\v1.5.0_E4B_zip`: E4B ZIP을 푼 시험 폴더.

## 7. GitLab 배포 준비

GitLab 서버의 푸시 전 보안 검사(Gitleaks, Semgrep)가 첫 푸시를 거절해 다음을 고쳤습니다. 같은 도구(Gitleaks 8.30.1, Semgrep 1.178.0)로 로컬에서 서버 결과(Gitleaks 90건, Semgrep 7건)를 재현한 뒤 수정했습니다.

- Gitleaks 90건은 모두 `quality/p0_repair/*/code_hashes.json`의 파일 해시를 API 키로 오인한 것입니다. 이 해시 목록 3개는 저장소에 넣지 않았습니다.
- Semgrep `use-defused-xml` 6건: 검증 도구 6개(`tools/validate_*.py`)가 pytest 결과 XML을 읽을 때 `defusedxml.ElementTree`를 쓰도록 바꿨습니다(쓰는 방법이 같은 대체 모듈, `requirements.txt`에 `defusedxml==0.7.1` 추가).
- Semgrep `dynamic-urllib-use-detected` 1건: 설치 점검 스크립트 `quality/packaging_v150_20260926/scripts/smoke_inst150.py`는 시험 기록이라 고치지 않고 저장소에서만 뺐습니다.
- 저장소에는 코드, 테스트, 문서, 사업 사전, 품질 결과 요약만 넣었습니다. 원문·DB 사본이 든 실행별 스냅샷과 위에서 뺀 파일을 포함한 전체 품질 기록은 구글 드라이브 소스 폴더 `seoguipowelfare-v1.5.0`에 있습니다.
- 설치 파일은 v1.4.0과 같은 방식으로 45MB 조각(E2B 59개, E4B 109개)과 복원 스크립트로 GitLab 패키지 레지스트리에 올립니다. 조각을 복원한 결과의 SHA-256이 원본과 같은 것을 이 PC에서 확인했습니다.
