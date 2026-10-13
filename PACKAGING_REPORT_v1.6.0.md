# v1.6.0 패키징 검증 기록

검증일: 2026-10-13. DB SHA-256: `21432e5432751dbbc5a75e70f2508d8a5c761ddadc3a8789017a4140e4884eee`.

- 전체 pytest: 363 passed, 1 warning, 511.27초.
- Ruff: 59건 미해결. 검사를 통과한 것으로 표시하지 않는다. GitLab CI 작업은 manual이다.
- E2B 설치 434초. 버전 1.6.0, AI Ready, 의미 검색 활성, 원문 113개·22,007개 구간 확인.
- E2B 설치된 DB SHA와 저장소 DB SHA 일치, bge-m3 SHA 일치, 사업 카드 포함 확인.
- E2B 4인 가구 긴급복지 생계지원 금액: 1,994,600원 (21.3초). 장애인전용주차 관련 원문 근거 응답 확인.
- E2B 종료 후 llama-server 잔류 0개. 무인 제거 성공.
- E4B 설치 1,658초. 설치된 파일·DB·bge-m3 SHA 일치. 기본 Vulkan 실행 두 차례 모델 로딩 시간 초과. CPU 실행도 Ready 확인 전 중단. 모델 응답 미검증. 무인 제거 성공.
- E2B 조각 9개 합친 파일 SHA 일치: `eb7d788fd6c3b1d02adb0f68ef34c9ce82c23cf27f7ea5344e576c0eb7d662c8`. 도우미 전체 실행 완료는 아직 미확인.
- 실제 빌드 폴더 합계: E4B 5,401,843,483바이트, E2B 3,806,518,683바이트(E4B 모델 크기를 E2B 모델 크기로 치환).
- 배포 스크립트의 이전 런타임 표기 두 군데를 b11565로 수정. 이 파일은 220 pure LOC이며 기존 구조를 유지했고 실행 기능 변경은 없다. 구문 분석 통과.

## 설치 파일

| 파일 | 크기(바이트) | SHA-256 | GitLab 조각 |
| --- | ---: | --- | --- |
| `BokjiTalkAI_Setup_v1.6.0_E2B.exe` | 3,286,291,798 | `eb7d788fd6c3b1d02adb0f68ef34c9ce82c23cf27f7ea5344e576c0eb7d662c8` | .001~.009 (9개) |
| `BokjiTalkAI_Setup_v1.6.0_E4B.exe` | 2,419,341 | `2bf1dc5a26dfd7e6f43ab9dccba19d5e74e23e0d3582f51d9536b0d3e0b88794` | 나누지 않음 |
| `BokjiTalkAI_Setup_v1.6.0_E4B-1.bin` | 1,897,580,288 | `f459079afffc4cb3e664e807ee74a41ac6bd1da65a017d87c5f9daed332d2462` | .001~.005 (5개) |
| `BokjiTalkAI_Setup_v1.6.0_E4B-2.bin` | 1,900,000,000 | `876dcbf701afc0235ff8e2a9aa2ef962dcf6f0fb1dedf8c8b6a8c4b40266dc31` | .001~.005 (5개) |
| `BokjiTalkAI_Setup_v1.6.0_E4B-3.bin` | 1,013,246,354 | `b093a9b7bb21aa3e7f84823f5c869aaa18aeb3f4d54d7bc83e0e15d8962cfe39` | .001~.003 (3개) |

SHA-256 조각·도우미 목록은 GitLab 패키지의 `SHA256SUMS_GITLAB_v1.6.0.txt`를 사용한다.

## 평가

민원 200: 정답 84·부분 52·보류 41·오답 23. 기존 250: 수치 50 핵심값 50/50, 일반 200 구조상 완결 171. 두 세트는 튜닝에 사용했으며 독립 평가가 아니다.
