# v1.4.0.Beta 패키징 상태

## 2026-09-26 (2차): 보안 수정, 설치 파일 생성, 설치·제거 시험

1차 점검에서 찾은 웹 보안 결함 2건과 화면 문구를 고친 뒤, E2B·E4B 설치 파일(setup.exe)을 만들어 이 PC에서 설치 → 실행 → 제거까지 시험했습니다. 모든 항목이 통과했습니다.

### 수정 (웹 계층만)

| 문제 | 수정 | 파일 |
|---|---|---|
| 외부 웹페이지가 `POST /api/shutdown`으로 앱을 종료함(CSRF) | POST·PUT·PATCH·DELETE는 Origin이 없거나 같은 출처(`http://127.0.0.1:8766` 등)일 때만 처리, `Sec-Fetch-Site: cross-site`는 403. 종료 API는 JSON 본문(`{}`)을 요구해 폼·text/plain 요청이 422 | `welfare_web.py`, `web/app.js`(종료 버튼이 JSON 전송) |
| Host 헤더 미검사(DNS 리바인딩 여지) | Host가 `127.0.0.1`·`localhost`가 아니면 400. 거절 응답에도 보안 헤더 유지 | `welfare_web.py` |
| 첫 화면 "38개 복지 매뉴얼" 고정 문구 | 상태 API의 실제 문서 수로 표시(39개), 쇼케이스 페이지 수치 수정 | `web/index.html`, `web/app.js`, `web/showcase.html` |

- 회귀 방지: `tests/test_web_local_guard.py` 6건(외부 Host 거절, 외부 출처·`null`·다른 포트·https 출처의 종료 요청 거절, 본문 없는/text/plain/폼 종료 요청 422, 같은 출처와 Origin 없는 로컬 클라이언트 허용, 외부 출처 질문 거절, 화면의 JSON 종료 요청과 실제 문서 수 표시).
- 기존 `tests/test_welfare_web.py`는 테스트 클라이언트 주소를 실제 앱 주소(`http://127.0.0.1:8766`)로 맞췄고, 종료 테스트는 새 계약에 맞춰 `json={}`로 보냅니다. 확인 내용은 줄이지 않았습니다.
- 전체 pytest **302 passed**(`quality/final_pytest/20260926T072020Z`), P0 replay 통과(`quality/p0_repair/20260926T072453313566Z`, 금액 골드 15/15, 원본 불변).
- A1_READY 판정 스냅샷(final_r3)과 비교해 바뀐 파일은 `welfare_web.py`와 `web/` 3개뿐이고, 검색·답변·검증 코드는 같습니다.

### 설치 파일

- 도구: Inno Setup 6.7.3(공식 GitHub 릴리스, "Pyrsys B.V." 서명 유효, 설치 파일 SHA-256 `9c73c3ba…b732`)을 현재 사용자 계정에 설치(`%LOCALAPPDATA%\Programs\Inno Setup 6`).
- 빌드: `build-exe.ps1 -ModelVariant E2B`·`E4B`(설치 파일 포함). E4B는 2GB 미만 분할 파일 3개와 배포용 ZIP이 함께 만들어집니다.
- 체크섬: `dist/SHA256SUMS_v1.4.0.Beta_20260926.txt`(사본 `quality/packaging_20260926/`).

| 배포 파일 | 크기(바이트) | SHA-256 |
|---|---:|---|
| `BokjiTalkAI_Setup_v1.4.0.Beta_E2B.exe` | 2,620,334,389 | `68fade3c610d1cd03d7f79af6f283f17fe330160df32e23aeddcbab395729cc9` |
| `BokjiTalkAI_Setup_v1.4.0.Beta_E4B.exe` | 2,410,625 | `62f532bfc30d703e7c0bdbbcc82113387c1dd4e013ec746c3b4b298911e99292` |
| `BokjiTalkAI_Setup_v1.4.0.Beta_E4B-1.bin` | 1,897,588,992 | `f0b3e3d7da988d6bf12c89532853a98892e410e8666c6b0546762c06a1fdc82c` |
| `BokjiTalkAI_Setup_v1.4.0.Beta_E4B-2.bin` | 1,900,000,000 | `17a009df7567e91a5f582d17854facc2e7966096f9cd7443987572196a2aec97` |
| `BokjiTalkAI_Setup_v1.4.0.Beta_E4B-3.bin` | 1,082,536,997 | `90b169b6d620cbad5c7ceba21274afca1c65a5908813ca4b1bf823e29b30cd7d` |
| `BokjiTalkAI_Setup_v1.4.0.Beta_E4B.zip` (위 4개 묶음) | 4,882,145,951 | `ab142bdeb3a3234dd96c37e6b39059651b855bc323c384c138d44091aff6ec43` |

### 설치 → 실행 → 제거 시험 (이 PC, 현재 사용자, 무인 설치 `/VERYSILENT`)

| 단계 | E2B | E4B |
|---|---|---|
| 설치 | 종료 코드 0, 178초, 234개 파일 | 종료 코드 0, 212초(분할 파일), 234개 파일 |
| 설치 위치·등록 | `%LOCALAPPDATA%\BokjiTalkAI_Beta_E2B`, 제거 목록 "복지톡AI v1.4.0.Beta E2B", 바탕화면·시작 메뉴 바로가기 | `…\BokjiTalkAI_Beta_E4B`, 같은 구성 |
| 설치본 무결성 | DB·모델 해시가 검증값과 같음, 실행 파일 해시가 빌드 산출물과 같음 | 같음 |
| 준비 시간 | 12.9초 | 12.7초 |
| 단일 금액(4인) | 59.6초, 1,994,600원 | 172.0초, 표 복구로 월 1,994,600원 |
| 연도 불일치(2025년 긴급복지) | 0.3초, 결정론적 안내 | 0.3초, 같음 |
| 외부 Host 조회 | 400 | 400 |
| 외부 출처 질문 / 종료(text/plain) | 403 / 403, 앱 유지 | 403 / 403, 앱 유지 |
| 출처 없는 text/plain 종료 | 422, 앱 유지 | 422, 앱 유지 |
| `Sec-Fetch-Site: cross-site` 종료 | 403 | 403 |
| 같은 출처 JSON 종료 | 200, 서버·llama-server 종료 | 200, 같음 |
| 화면 종료 버튼(내장 브라우저에서 클릭) | "복지업무 비서를 종료했습니다" 표시, 서버·llama-server 종료, 대기 포트 0 | — |
| 로그의 질문 원문 | 0건 | 0건 |
| 제거 | 종료 코드 0, 4초, 설치 폴더·제거 목록·바로가기·시작 메뉴 폴더 모두 삭제 | 같음 |

기록: `quality/packaging_20260926/installers/`(빌드·설치·제거 로그, 설치본 점검 결과). E2B 설치의 Inno Setup 로그는 E4B 설치 로그에 같은 파일명으로 덮어써져 남지 않았습니다(E2B 설치 결과는 위 표와 점검 결과 파일에 기록).

### 남은 항목

깨끗한 PC(개발 도구 없는 PC) 설치, 8GB·16GB 업무용 PC 인수, 인터넷 차단 상태 시험, 코드 서명(현재 설치 파일은 서명되지 않음), 롤백 패키지, 배포 승인 후 체크섬 확정.

---

## 2026-09-26 (1차): 최종 코드 실행 폴더 빌드와 이 PC 실행 점검

아래 실행 폴더와 해시는 보안 수정 전 빌드입니다. 두 폴더는 2차 빌드로 대체했고, 점검 기록은 `quality/packaging_20260926/`에 남아 있습니다.

A1_READY 판정 코드(final_r3 소스 스냅샷 `059569…befe`와 앱 코드 45개 파일 해시 일치)로 E2B·E4B 실행 폴더를 빌드하고 이 검증 PC에서 실행했습니다. 이 PC에는 Inno Setup이 없어 **설치 파일(setup.exe)은 만들지 않았습니다**(`build-exe.ps1 -SkipInstaller`). 설치·제거 시험과 다른 PC 인수는 하지 않았습니다.

### 빌드

- 환경: `.venv-package`(Python 3.12, `requirements-build.txt` 고정 버전, PyInstaller 6.16.0).
- 자산: 검색 DB는 검증에 쓴 `quality/real_ab/20260920T140405942320Z/common_db`를 `wiki/kb-v120`에 복사, llama-server(b10686 Vulkan)와 모델은 `seoguipowelfare-runtime-assets`에서 가져옴.
- 경고: `webview.platforms.android`, `pycparser.lextab/yacctab`, `tzdata` 미수집 경고만 있음(실행 영향 없음).
- 로그: `quality/packaging_20260926/build_e2b.log`, `build_e4b.log`.

| 산출물 (dist) | 파일 수 | 크기 | 실행 파일 SHA-256 |
|---|---:|---:|---|
| `BokjiTalkAI_v1.4.0.Beta_E2B` | 232 | 3,047,175,579바이트 | `4772b24b3e60640a82e5d51efdc36769816d1e65ad142adda2fdaba48c8964cf` |
| `BokjiTalkAI_v1.4.0.Beta_E4B` | 234 | 5,403,976,187바이트 | `e89ced07eaa581833ad2daf4d09dbc95eac060621cec67390237215321d63076` |

두 폴더의 번들 자산은 검증 해시와 같습니다: DB `695f7ae1…1d02`, llama-server `79f9eee9…a735`, 사업 사전 `71c890ed…c22d`, E2B 모델 `e5310072…6889`, E4B 모델 `85a896a0…ab87`. 실행 후에도 DB 해시는 바뀌지 않았습니다.

### 실행 점검 (이 PC, 로컬 API로 질문)

| 빌드 | 준비 | 질문 | 결과 |
|---|---|---|---|
| E2B | llama-server 7.7초 | 긴급복지 4인 가구 금액 | 53초, 1,994,600원, 완결 |
| | | 지역사회보장협의체 업무 기준 | 68초, 27번 지침 근거, 완결 |
| | | 기초연금 신청 절차 | 96초, 05번 기초연금 매뉴얼 근거, 부분 |
| | | 2025년 긴급복지 소득기준 | 0.2초, 연도 불일치 안내(모델 호출 없음) |
| | | 노숙인 복지 신청 절차 | 115초, 26번 노숙인 매뉴얼 근거, 완결 |
| E4B | llama-server 13.2초 | 긴급복지 1인 가구 금액 | 149초, 표 복구로 월 783,000원, 완결 |
| | | 2025년 긴급복지 소득기준 | 0.6초, 연도 불일치 안내 |
| | | 지역사회보장협의체 업무 기준 | 208초, 27번 지침 근거, 완결 |

- 화면: 첫 화면이 정상 표시되고 시스템 상태 "정상", 복지 매뉴얼 39개, 검색 구간 21,588개. E2B 빌드에서는 E4B 선택지가 비활성입니다(`quality/packaging_20260926/smoke_e2b_ui.png`).
- 네트워크: 웹서버(8766)와 llama-server(18081)는 127.0.0.1에서만 대기했고, 질문 처리 중 루프백이 아닌 TCP 연결은 0건이었습니다. 방화벽으로 인터넷을 막은 상태의 시험은 하지 않았습니다.
- 로그: 앱 로그에 질문 원문이 남지 않았습니다(`raw_query_logging=false`).
- 종료: 종료 API로 앱과 llama-server가 함께 종료되고 남는 프로세스가 없었습니다.

### 발견한 문제 (2차에서 수정)

1. **다른 웹페이지가 앱을 끌 수 있음(CSRF)**: `POST /api/shutdown`은 출처(Origin)를 검사하지 않고 본문도 요구하지 않습니다. Origin을 `http://evil.example`로 둔 text/plain 요청 하나로 로컬 서버와 llama-server가 종료됐습니다. 사용자가 브라우저로 악성 페이지를 열면 복지톡이 강제 종료될 수 있습니다(데이터 유출은 아님).
2. **Host 헤더 미검사**: Host를 `evil.example`로 둔 요청도 200으로 처리합니다. DNS 리바인딩으로 외부 페이지가 상태 조회와 질문을 할 여지가 있습니다. 질문 API는 JSON 외 형식을 422로, CORS 사전 요청을 405로 거절해 일반적인 교차 출처 호출은 막힙니다.
3. 첫 화면 문구는 "38개 복지 매뉴얼 통합 검색"인데 실제 매뉴얼은 39개입니다.

권장 수정: 웹 미들웨어에서 Host가 `127.0.0.1:8766`·`localhost:8766`이 아니면 거절하고, POST 요청은 Origin이 없거나 같은 출처일 때만 받으며, 종료 API는 JSON 본문이나 전용 헤더를 요구합니다. 수정하면 pytest와 설치본 점검을 다시 해야 합니다.

### 남은 항목

setup.exe 생성(Inno Setup 필요), 설치·제거 E2E, 깨끗한 PC 설치, 8GB·16GB 업무용 PC 인수, 인터넷 차단 상태 시험, 롤백 패키지, 코드 서명, 최종 배포파일 SHA 고정.

---

## 이전 기록 (2026-09-20)

확인일: 2026-09-20

## 현재 산출물

별도 소스 프로젝트: `C:\Users\USER\Documents\Codex\seoguipowelfare-v1.4.0.Beta`.

앱 표시 버전 `v1.4.0.Beta`, VERSION 값 `1.4.0.Beta`, Windows 숫자 버전 `1.4.0.1`로 수정했다. 웹 기본 포트는 8766, 모델 서버는 18081이며 정식판 포트를 사용하지 않는다. 설치 식별자와 설치 폴더는 `BokjiTalkAI_Beta_E2B` 또는 `BokjiTalkAI_Beta_E4B`로 분리했다. 이 항목은 소스 설정 확인이며 실제 설치시험 결과가 아니다.

## 실제 파일 확인

| 자산 | Beta 소스 폴더 상태 |
|---|---|
| source-md 원문 | 원본 프로젝트에서 복사됨 |
| models 폴더 | 없음: 검증 스크립트 확인 |
| runtime/llamacpp/llama-server.exe | 없음: 검증 스크립트 확인 |
| wiki/kb-v120/welfare.db | 없음: 커넥터 파일 존재 조회 확인 |
| 신규 Beta EXE / 설치파일 | 빌드하지 않음 |

따라서 이 소스 폴더를 실행 가능한 전체 설치 패키지라고 안내하지 않는다. 원본 정식판 EXE의 이름만 변경하여 Beta로 배포하지 않는다.

## 검증 경계

2026-09-20 최종 코드 회귀시험은 146개 전부 통과했고, 실패·오류·건너뜀 0개, 기존 라이브러리 경고 2개였다. 이는 패키징 완료가 아니다. 실제 GGUF 추론, 새 EXE 생성, 설치·화면·롤백 시험은 여전히 미수행이다. 상세 결과는 `QUALITY_REPORT_v1.4.0.Beta.md`를 따른다.

기존 가상환경 `seoguipowelfare/deploy-current/.venv-openkb`의 Python과 설치된 패키지를 읽기 사용했다. 원본 v1.4.0 및 기존 가상환경에 패키지 설치·업데이트를 수행하지 않았다. 해당 환경에서의 pytest 결과는 requirements.txt에 고정된 모든 버전의 재현 검증이나 깨끗한 PC 설치시험을 의미하지 않는다. 실제 설치된 패키지 버전은 재검증 JSON에 기록한다.

단일 토큰 선택 어댑터는 코드/모의 응답 시험과 실제 GGUF·서버 호환성 시험을 구분한다. 기본 OFF를 유지하며 외부 모델 다운로드·클라우드 대체·E4B 자동 전환을 수행하지 않는다.

출시 전에는 고정한 모델/서버 바이너리·원문 DB의 조합으로 답변 및 단일 토큰 호환성을 측정하고, 설치·망 차단·포트 분리·롤백을 실제 실행해 확인해야 한다. 이번에 이러한 시험을 완료한 것으로 보고하지 않는다.
