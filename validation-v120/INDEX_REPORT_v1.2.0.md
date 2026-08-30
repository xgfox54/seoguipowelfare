# INDEX_REPORT_v1.2.0.md

- build_timestamp: 2026-08-31 00:06 (Asia/Seoul, 2회 실행 확인: 1차 신규빌드, 2차 증분빌드)
- source_count: 38
- source_bytes: 61234862
- node_count: 93956
- section_count: 18649
- FTS count (sections_fts): 18649
- embedding_count: 0 (nomic-embed-text-v2-moe 미설치, 사용자 판단 보류 중)
- references_count: 41929
- quality_issue_count: 0
- avg_chunk_chars: 1752.1
- min_chunk_chars: 43
- max_chunk_chars: 2800
- DB_size_MB: 266.9 (279887872 bytes)
- build_duration_1st_run_s: ~100 (전체 재색인)
- incremental_rebuild_duration_s: 0.41 (변경 없음, SHA-256 기반 skip 확인)
- embedding_model: N/A (미설치)
- embedding_duration: N/A
- pytest: 27 passed, 0 failed (2 warnings, deprecation only)
- E2E: PASS (welfare_launcher.py 실제 진입점으로 /api/status, /api/ask 3건 모두 200 응답 확인)
- 최종 판단: HOLD (아래 결론 참조)

## 원문 무결성

38/38 exact reconstruction 성공 (byte-for-byte, source-md 원본과 완전히 일치).

## 품질 오류

- quality_issues 테이블: 0건 (blocking, warning 모두 없음)
- content_hash 중복: 22건 확인. 이 중 21건은 같은 문서 안에서 서로 다른 start_line/end_line을
  가진 별도 섹션으로, 원문 자체에 동일한 표/서식이 문서 내 여러 위치에 반복 등장하는 경우다
  (예: 신청서 양식, 발행 정보 박스). 저장 로직 버그로 인한 중복 저장이 아니라 원문의 실제
  중복이므로 blocking으로 보지 않는다. 1건은 서로 다른 두 문서 간 우연 일치.
- 최소 청크 43자(<800자 MIN_SECTION_CHARS 기준 미달) 19건 확인. 대부분 heading 없는 표
  꼬리/발행정보 박스 등 원문 구조상 자연스러운 짧은 조각이며, quality_issues에 별도 기록되지
  않았다. blocking 기준(원문 유실/표 유실/빈 청크/인코딩 오류)에는 해당하지 않으나, MIN_SECTION_CHARS
  하한이 실제로 강제되지 않는 사례로 남는다.

## 검색 구조

- FTS fallback: embeddings 테이블이 비어 있는 현재 상태에서 `semantic_section_ids()`가 빈
  튜플을 반환하고 `search_sections()`가 예외 없이 FTS 결과만 반환함을 직접 실행으로 확인.
  잘못된 모델명으로 `_embed()`를 호출해도 빈 리스트를 반환하며 예외를 던지지 않음을 확인.
- 증분 색인: 동일 소스로 재빌드 시 0.41초에 완료(전량 스킵), content_hash 기반 resume 정상.

## 검색 A/B (8개 원문 질의, 인수인계서 문구 그대로)

- Recall@6 v1.0.2: 2/8
- Recall@6 v1.2.0 FTS: 7/8
- v1.2.0 Semantic Hybrid: 미실시 (임베딩 모델 미설치)

## Held-out(문구 변형) 재검증 - 중요

- Recall@6 v1.0.2: 1/8
- Recall@6 v1.2.0 FTS: 2/8

8개 원문 질의에서 관측된 큰 개선폭은 대부분 `welfare_search/search.py`의
`QUERY_EXPANSIONS`(정규식 7개, 차/차량, 병원 동행, 집에서 돌봄, 월세, 출산, 목욕, 생활비 등)
가 이 8개 질의의 정확한 문구와 맞춰 하드코딩되어 있기 때문으로 판단된다. 같은 의도를 다른
표현으로 재구성한 held-out 질의에서는 개선폭이 1/8->2/8로 거의 사라진다. 즉 청킹/계층
구조 개선 자체는 유효하지만, "생활어 질의 일반화"라는 목표는 현재 FTS 단독 구조로는
아직 달성되지 않았고, semantic 검색(nomic-embed-text-v2-moe)이 없는 상태에서는
QUERY_EXPANSIONS 목록에 없는 질문에 대한 개선을 보장할 수 없다.

## 네트워크 격리

실행 중 프로세스의 TCP 연결을 확인한 결과 127.0.0.1:8765(자체 서버)만 LISTEN 상태였고,
외부로 나가는 연결은 관측되지 않았다.

## 앱 종료/프로세스 정리

`welfare_launcher.py`(실제 EXE 진입점)를 직접 실행해 `/api/status`, `/api/ask` 경로가
정상 동작함을 확인했다. `/api/shutdown` 호출 시 uvicorn 서버는 정상 종료되어 포트 8765
리스너가 사라졌다(정상 창 사용 시에는 여기에 더해 pywebview 창의 close 콜백이
`window.pywebview.api.close_app()`를 통해 프로세스 전체를 정리하는 구조이며, 코드로
직접 확인했다). 테스트에 사용한 프로세스는 CommandLine을 확인해 이번 세션의 PID만
골라 종료했고, 다른 python.exe 프로세스는 건드리지 않았다. 종료 후 wiki/kb-v120에는
wal/shm/journal lock 파일이 없었다.

## v1.0.2 / v1.1.0 미변경 확인

- v1.0.2/dist/복지업무비서.exe: 93,307,737 bytes, LastWriteTime 2026-08-30 16:45:46 (작업 전후 동일)
- v1.1.0 폴더: LastWriteTime 2026-08-30 23:05:54 (작업 전후 동일)
- git status(deploy-current 상위): clean, v1.0.2/v1.1.0 관련 변경 없음

## 아이콘 반영 확인 (이전 웹GPT 세션 작업)

v1.0.2에서 작업한 복지톡 아이콘(`assets/bokjitalk.ico`, SHA-256 9BE8B048...F12F0964)이
v1.2.0에도 바이트 단위로 동일하게 존재하며, `복지업무비서.spec`의 PyInstaller datas/EXE
icon 설정과 `welfare_launcher.py`의 pywebview `icon=` 인자에도 동일하게 배선되어 있다.
