# 복지톡AI 복지업무비서 v1.2.0

## 목적

v1.0.2 및 기존 v1.1.0 작업본을 보존한 상태에서 검색 정확도와 근거 추적성을 개선한 별도 롤백 가능 버전이다.

## 주요 변경

- 검색 청크를 기존 3,000~12,000자 구조에서 목표 1,800자, 최소 800자, 최대 2,800자 구조로 세분화
- Markdown 제목 계층을 `nodes` 테이블로 보존하여 장/절/항목 경로 추적
- `documents`에 문서종류, 발행기관, 판본, 시행 시작일/종료일 메타데이터 저장
- 문서 해시 기반 증분 색인 적용
- SQLite FTS5/BM25 검색 유지
- 로컬 Ollama 임베딩이 구축된 경우 RRF 방식으로 FTS와 semantic 결과를 결합
- 임베딩이 없거나 Ollama embedding API를 사용할 수 없는 경우 FTS만으로 자동 폴백
- 생활어 질의를 행정용어로 보완하는 제한적 query expansion 적용
- search 결과 ID와 실제 원문 evidence fetch를 분리
- 법령명/조문/별표·별지 참조를 `references_map`에 추출
- 청크 초과, 인코딩 손상, 빈 청크, 제목 누락 등 품질 이슈를 `quality_issues`에 기록
- manifest에 스키마 버전, 청킹 설정, 참조 수, 품질 이슈 수 기록

## 롤백

문제 발생 시 `work/seoguipowelfare-v1.0.2` 또는 기존 배포본을 그대로 사용한다. v1.2.0 작업은 해당 디렉터리 밖의 이전 버전 파일을 수정하지 않는다.

## 하이브리드 검색 주의사항

현재 PC에는 생성용 `gemma4:e2b-it-qat`, `gemma4:e4b`만 설치되어 있고 별도 임베딩 모델은 확인되지 않았다. 따라서 v1.2.0은 기본적으로 FTS5 개선 검색으로 동작하며, 추후 로컬 Ollama embedding 모델을 설치하고 `python welfare_index.py embed <model>`을 실행하면 semantic hybrid 검색이 자동 활성화된다.
