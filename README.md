![서귀포시 복지톡 AI 배너](docs/banner.png)

# 서귀포시 복지톡(Talk) AI 업무비서(로컬PC용)

복지 업무자료 39개를 **로컬 SQLite FTS 검색색인**으로 검색하고, 프로그램에 **내장된 llama.cpp 엔진과 Gemma 4 모델**이 검색된 원문만 근거로 답변하는 Windows용 개인 업무 도구입니다. 선택한 설치 패키지로 AI 엔진과 모델까지 함께 설치되므로 Ollama 등 별도 프로그램 설치가 필요 없습니다.

> **v1.3.4:** 합본 문서의 다른 사업 조건과 잘못된 연도가 답변에 섞이지 않도록 검색 순위와 자동 근거 검수를 강화했습니다. [v1.3.4 릴리스](https://gitlab.aigov.go.kr/memory365/seoguipowelfare/-/releases/v1.3.4)에서 원하는 모델을 선택하세요.

`복지업무비서_v1.3.4_E2B.exe` 또는 `복지업무비서_v1.3.4_E4B.exe`를 실행하고 업무에 필요한 내용을 검색하면 Gemma4 e4b, e2b가 답변해줍니다.

OpenAI API, ChatGPT Plus, OpenKB, OpenAI Agents SDK는 실행에 필요하지 않습니다.

(다운로드 페이지 링크)
https://gitlab.aigov.go.kr/memory365/seoguipowelfare/-/releases

## 현재 버전 한눈에 보기

| 항목 | 현재 구현 |
| --- | --- |
| 버전 | v1.3.4 |
| 사용자 실행 파일 | `복지업무비서.exe` 단일 파일 |
| 화면 | pywebview + Microsoft Edge WebView2 기반 독립 프로그램 창 |
| 로컬 서버 | FastAPI / Uvicorn, `127.0.0.1:8765`에만 바인딩 |
| 검색 | SQLite FTS5/BM25 + 선택적 로컬 semantic hybrid 검색 |
| 복지 업무자료 | 39개 Markdown 원문 |
| 검색 구간 | 21,588개 |
| 원문 총량 | 62,075,154바이트 |
| 기본 AI 모델 | Gemma 4 E2B QAT Q4 (`gemma4-e2b-it-qat.gguf`, 설치 파일에 내장) |
| E4B 패키지 | Gemma 4 E4B Q4_K_M (`gemma4-e4b.gguf`, E4B 패키지에 내장) |
| AI 호출 방식 | 내장 llama-server(llama.cpp b10834) OpenAI 호환 API, 127.0.0.1:18080 |
| 인터넷 필요 여부 | 패키지 다운로드 후 설치와 일반 질의는 오프라인 가능 |

## v1.3.4 주요 변경

- 합본 파일명이 검색 순위를 오염시키지 않도록 사업 소속을 문서 전체가 아니라 구간 제목과 본문 기준으로 판정합니다.
- 질문에 특정 연도가 있으면 다른 연도를 현행 기준이나 대체 결론으로 제시한 문장을 자동으로 제외합니다.
- 모델이 답변에 추가한 수치·금액·급여명 중 검색 원문에서 확인되지 않는 문장을 자동으로 제외하고 화면에 검수 결과를 표시합니다.
- 첫 답변 생성이 실패해 대체 경로를 사용하더라도 품질감독과 자동 근거 검수를 동일하게 적용합니다.
- 긴 HTML 표가 여러 개 있는 구간에서는 질문과 가장 관련 있는 표를 선택하고, 표 바로 뒤의 단위·각주를 함께 전달합니다.
- 감독 모델 호출에 실패하면 검수 전 답변임을 화면에 분명히 표시합니다.
- AI가 같은 문장을 반복 출력하면 중복 문장을 제거합니다.
- 사업이 실제로 수록된 매뉴얼이, 그 사업을 지나가듯 언급한 다른 자료보다 먼저 근거로 쓰입니다.

## v1.3.3 주요 변경

- 합본 문서에서 각 검색 구간이 자기 본문에 실제로 나오는 사업명만 갖도록 색인 방식을 바꿨습니다. 이전에는 파일 전체의 사업명이 모든 구간에 복사되어 다른 사업의 내용이 함께 검색됐습니다.
- 문서 길이가 검색 순위에 유리하게 작용하던 편향을 제거하고, 질문 용어를 실제로 담은 구간을 우선합니다.
- 원본 자료와 요약본을 구분하는 값을 잘못 읽던 오류를 고쳐 원본 매뉴얼이 먼저 근거로 쓰입니다.
- 질문의 여러 조건을 모두 만족하는 구간을 별도로 찾아 후보에 추가합니다.
- HTML 표와 Markdown 표가 중간에서 잘리지 않고 한 구간에 보존됩니다. 모델에 넘길 때는 표 제목·머리말과 질문 관련 행을 남기고 나머지를 생략 표시로 줄입니다.
- 한 사업의 대상·금액·기간·신청 절차가 같은 매뉴얼에 있어도 함께 근거로 전달됩니다.
- 같은 복지 질문 50개 기준으로, 필요한 수치까지 근거에 포함된 질문이 37개에서 50개로 늘었고 검색 시간은 평균 2.67초에서 1.00초로 줄었습니다.

## v1.3.2 주요 변경

- Ollama 의존성 제거: 설치 확인, 서비스 실행, 11434 포트, `ollama pull` 안내가 모두 사라졌습니다.
- llama.cpp(b10834, Vulkan 빌드)와 Gemma 4 E2B QAT GGUF 모델을 설치 패키지에 내장했습니다.
- 프로그램 실행 시 `runtime\llamacpp\llama-server.exe`를 자동 시작하고 `models\*.gguf`를 자동 탐색합니다.
- 프로그램 종료·강제종료 시 Windows Job Object로 llama-server가 함께 정리됩니다.
- 화면에 AI 엔진 상태(시작 중 → 모델 불러오는 중 → 실행 중)와 오류 원인을 표시합니다.
- E2B는 단일 설치 EXE, E4B는 설치 EXE와 분할 데이터를 묶은 ZIP으로 제공합니다.
- [RELEASE_NOTES_v1.3.3.md](RELEASE_NOTES_v1.3.3.md)에서 전환 상세를 확인할 수 있습니다.

## v1.3.1 주요 변경

- 복지DB 6차 업데이트 원문 39개 및 재생성된 검색색인을 EXE에 내장했습니다.
- Windows EXE 파일·제품 버전을 1.3.1로 표시합니다.
- [RELEASE_NOTES_v1.3.1.md](RELEASE_NOTES_v1.3.1.md)에서 변경 자료와 설치 방법을 확인할 수 있습니다.

## v1.3.0 주요 변경

- 복지톡 전용 아이콘(둥근 모서리, 완전 투명 모서리)을 웹 헤더, 브라우저 파비콘, EXE, 작업표시줄에 통일 적용
- 검색 결과 화면에 **결과 내 검색** 입력창과 이전/다음 이동 버튼 추가
- **답변에 걸린 시간** 표시 위치를 검색 결과 제목 옆으로 이동
- Ollama 미설치/미실행 시 설치 안내 다이얼로그 추가 (Ollama 다운로드 페이지 바로가기, 모델 설치 명령 복사, 설치 상태 다시 확인 버튼 포함)
- Ollama 실행 파일 탐색 로직을 표준 설치 경로까지 확인하도록 보강
- 개인정보 경고 문구를 로컬 처리 안내로 교체
- HTTP(S) 스킴만 허용하는 내부 통신 헬퍼 도입 및 의존성 버전 고정으로 GitLab 보안 스캔(Semgrep, OSV-Scanner) 통과

전체 변경 이력은 [RELEASE_NOTES_v1.3.0.md](RELEASE_NOTES_v1.3.0.md)를 참고하세요.

## 일반 사용자: 설치 파일 하나로 실행하기

### 1. 필요한 것

일반 사용자는 Python, Git, Ollama 등 어떤 프로그램도 미리 설치할 필요가 없습니다.

1. **Windows 10/11 (64bit)**
2. **여유 디스크 약 4GB, 여유 메모리 4GB 이상**

프로그램 창은 Microsoft Edge WebView2 런타임을 사용합니다. Windows 11과 최신 Windows 10 환경에는 보통 이미 설치돼 있습니다.

### 2. 설치

릴리스 페이지에서 원하는 패키지를 내려받습니다.

- **E2B:** `BokjiTalkAI_Setup_v1.3.4_E2B.exe`를 실행합니다.
- **E4B:** `BokjiTalkAI_Setup_v1.3.4_E4B.zip`을 폴더에 모두 풀고, 안의 `복지톡AI_Setup_v1.3.4_E4B.exe`를 실행합니다. `.bin` 파일은 설치 EXE와 같은 폴더에 있어야 합니다.

두 패키지 모두 AI 엔진, 해당 모델, 웹 화면, 복지 검색 DB를 포함합니다. 모델이나 Ollama를 별도로 설치할 필요가 없습니다.

E2B는 `%LOCALAPPDATA%\BokjiTalkAI`, E4B는 `%LOCALAPPDATA%\BokjiTalkAI_E4B`에 설치됩니다. 관리자 권한 없이 설치할 수 있습니다. 두 버전은 한 번에 하나씩 실행하세요. 실행 화면 상단에 `v1.3.4`가 표시됩니다.

### 3. 실행

시작 메뉴 또는 바탕화면의 **복지톡AI 복지업무비서**를 실행하면 다음이 자동으로 진행됩니다.

1. 이미 프로그램이 실행 중인지 확인합니다.
2. `127.0.0.1:8765` 포트 사용 여부를 확인합니다.
3. 내장 AI 엔진(`llama-server.exe`)을 `127.0.0.1:18080`에 시작하고 `models\` 폴더의 GGUF 모델을 자동으로 불러옵니다.
4. 복지 검색 DB와 FastAPI 서버를 시작합니다.
5. **서귀포시 복지톡(Talk) AI 업무비서(로컬PC용)** 프로그램 창을 엽니다.

모델을 메모리에 올리는 데 PC 사양에 따라 10초~1분 정도 걸립니다. 그동안 화면에 `AI 준비 중` 상태가 표시되고, 준비가 끝나면 질문 버튼이 활성화됩니다.

### 4. 화면에서 AI 상태 확인

시스템 상태 영역에서 다음 항목을 바로 확인할 수 있습니다.

- **AI 연결**: 사용 가능한 모델이 있으면 `연결됨`
- **AI 엔진**: `시작 중` / `모델 불러오는 중` / `실행 중` / `오류`
- **Gemma 4 E2B**: 기본 내장 모델, 정상이면 `실행 중`
- **Gemma 4 E4B**: E4B 패키지에서 사용
- 복지 매뉴얼 수, 검색 구간 수, 현재 선택 모델

엔진이 `오류`로 표시되면 화면의 **문제 해결 안내**와 설치 폴더 `logs\llama-server.log`, `logs\welfare-app.log`를 확인하세요. 모델 파일 누락, 메모리 부족, 포트 충돌을 구분해서 안내합니다.
### 5. 프로그램 종료

다음 두 방법 모두 내부 로컬 서버까지 함께 종료합니다.

- 프로그램 창 닫기
- 화면 오른쪽 위 **프로그램 종료** 버튼 누르기

프로그램 창만 사라지고 서버가 계속 남아 있는 브라우저 기반 실행 방식은 현재 기본 배포 방식이 아닙니다.

## 사용 방법

1. 질문란에 확인할 복지업무 내용을 입력합니다.
2. 사용할 모델을 선택합니다.
3. `질문하기`를 누르거나 Enter를 누릅니다.
4. 검색된 복지DB 원문을 근거로 생성된 답변을 확인합니다. 답변이 길 경우 검색 결과 영역의 **결과 내 검색** 창으로 원하는 내용을 바로 찾을 수 있습니다.
5. 중요한 안내, 급여 결정, 행정처분 전에는 반드시 원문 지침을 다시 확인합니다.

질문과 검색 원문은 프로그램에 내장된 llama.cpp 엔진에서 처리되며 외부 AI 서비스로 전송하지 않습니다. 업무상 필요한 사례정보도 동일한 로컬 처리 경로를 사용합니다.

## 답변 처리 구조

현재 버전의 실제 처리 흐름은 다음과 같습니다.

```text
사용자 질문
   ↓
① 질문 정제 에이전트 (Query Refiner)
   - 제도·대상·업무단계·조건·적용연도를 구조화
   - 검색에 불필요한 표현 제거 및 복지업무 동의어·약칭 확장
   - 없는 법령명·수치·조건은 생성 금지
   ↓
SQLite FTS5/BM25 + 선택적 semantic hybrid 검색
   - 특정 연도 질문은 해당 연도 우선
   - 일반 질문은 최신·현행 자료 우선
   - 원본 업무자료(primary) 우선
   ↓
관련 복지 지침 구간 추출
   ↓
② 답변 에이전트 (Answer Agent)
   - 사용자 원문 질문 + 정제 질문 + 검색 원문 사용
   - 검색 원문만 근거로 답변 초안 생성
   ↓
③ 품질감독 에이전트 (Supervisor)
   - 초안과 동일한 검색 원문 대조
   - 근거 없는 사실·수치·자격조건 검사
   - 연도 혼합·구자료 사용·자료 간 기준충돌 검사
   - 사례형 질문의 누락 조건 및 과도한 적격·부적격 판정 검사
   - 필요 시 원문 범위 안에서 최종 답변 수정
   ↓
최종 답변
   ↓
프로그램 창에 Markdown 렌더링
```

세 에이전트는 별도의 외부 AI 서비스를 사용하지 않고 내장 llama-server의 **Gemma 모델을 역할별 프롬프트로 순차 호출**합니다. 따라서 질문과 복지DB 원문은 PC 밖으로 전송되지 않습니다.

검색 DB는 **6차 업데이트 원문 39개**를 사용합니다. `document_metadata.yaml`에서 각 합본 문서의 주제(`topic`), 근거 우선순위(`authority`), 자료 성격(`source_role`), 적용 범위(`jurisdiction`)를 별도로 관리합니다. `primary` 원본 업무자료를 최우선으로 사용하고, `reference`·`summary`·`index` 자료는 보조 근거로 취급합니다.

별도 로컬 법령 DB는 운영하지 않습니다. 법령명이나 조문은 검색된 매뉴얼 원문에서 실제 확인되는 범위에서만 안내하며, 로컬 모델의 일반지식으로 현행 법령 내용을 보충하지 않습니다.

장애 대응은 단계별 폴백으로 구성되어 있습니다. 질문 정제 단계가 실패하면 사용자 원문 질문으로 검색하고, 품질감독 단계가 실패하면 이미 복지DB 원문에 근거해 생성된 답변 초안을 반환합니다. 핵심 답변 생성 단계에서 오류가 발생하면 기존 단일 에이전트 프롬프트로 한 번 더 시도합니다.

### OpenKB 사용 여부

현재 실행 경로에서는 **OpenKB를 사용하지 않습니다.**

과거 버전에서 사용하던 `.venv-openkb` 가상환경 이름과 `setup-openkb.ps1` 파일명 일부는 기존 작업환경 및 스크립트 호환을 위해 남아 있지만, 현재 `requirements.txt`에는 OpenKB가 포함돼 있지 않으며 실행 시 `openkb.exe`도 필요하지 않습니다.

AI 답변은 `welfare_assistant.py`가 `welfare_llm.py`를 통해 내장 llama-server의 OpenAI 호환 API(`127.0.0.1:18080/v1/chat/completions`)를 호출해 생성합니다. Gemma 4 chat template은 llama-server의 `--jinja` 옵션으로 적용하고, thinking 모드는 끕니다.

## 모델

### Gemma 4 E2B QAT Q4 (기본, 설치 파일 내장)

- 파일: `models\gemma4-e2b-it-qat.gguf` (3,349,514,112바이트, Q4_0)
- 프로그램 모델 키: `gemma_e2b`
- 저사양 업무용 PC를 기준으로 선정한 기본 모델. 모델 로딩 후 약 4GB RAM 사용

### Gemma 4 E4B Q4_K_M (E4B 패키지 내장)

- 파일: `models\gemma4-e4b.gguf` (4,977,171,584바이트)
- 프로그램 모델 키: `gemma_e4b`
- 배포 모델: [Unsloth Gemma 4 E4B GGUF](https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF), `gemma-4-E4B-it-Q4_K_M.gguf`. E4B 패키지 설치 시 자동 포함됩니다.

두 모델 모두 내장 llama.cpp에서 실행되며 별도의 OpenAI API 요금은 발생하지 않습니다. 처리 속도와 답변 품질은 CPU, RAM, GPU, 모델 로딩 상태에 따라 달라집니다.

## 로컬 보안 구조

- FastAPI 서버는 `127.0.0.1`에만 바인딩됩니다.
- 웹 UI의 외부 폰트, 외부 스크립트, 통계/분석 서비스 의존성이 없습니다.
- Markdown 렌더링 시 원시 HTML은 비활성화합니다.
- 질문과 검색 원문은 내장 llama-server(`127.0.0.1:18080`, loopback 전용)로만 전달됩니다.
- 프로그램 자체는 답변 생성을 위해 외부 AI API를 호출하지 않습니다.
- 내부 HTTP 통신은 http/https 스킴만 허용하는 헬퍼를 거쳐 이뤄지며, GitLab 저장소의 서버 측 보안 스캔(Semgrep, OSV-Scanner 등)을 통과한 상태로 배포됩니다.

단, llama.cpp 바이너리와 GGUF 모델을 준비하거나 Git 저장소/패키지를 설치하는 개발 과정에서는 인터넷 연결이 필요합니다. 완성된 설치 파일은 인터넷 없이 설치·실행됩니다.

## 복지DB 기준

프로그램 v1.3.4 / 2026-09-07 복지DB 6차 업데이트 기준(검색 색인은 v1.3.3에서 재생성):

- 원문 문서: **39개**
- 원문 총량: **62,075,154바이트**
- 검색 구간: **21,588개**
- 검색 인덱스 DB: **286,445,568바이트 (약 273.2MiB)**
- 품질 오류: **0건**

EXE 빌드 시 다음 파일이 실행 파일 내부에 함께 포함됩니다.

```text
wiki/kb-v120/welfare.db
wiki/kb-v120/manifest.json
web/
config.yaml.example
```

따라서 완성된 EXE 사용자는 별도로 검색색인을 만들 필요가 없습니다.

## 개발자용: 소스에서 실행환경 구성

이 절은 **EXE 사용자에게는 필요하지 않습니다.** 복지 원문을 갱신하거나 EXE를 새로 빌드하는 개발자용 절차입니다.

### 준비물

- Windows 10/11
- Python 3.12
- Git
- llama.cpp Windows 빌드(b10834 vulkan-x64)를 `runtime\llamacpp\`에 압축 해제
- Gemma 4 E2B QAT GGUF 파일을 `models\gemma4-e2b-it-qat.gguf`로 배치
- Inno Setup 6 (설치 파일 생성용, `ISCC_PATH` 환경변수로 경로 지정 가능)

저장소 내려받기:

```powershell
cd $HOME\Documents
git clone https://gitlab.aigov.go.kr/memory365/seoguipowelfare.git 복지업무비서
cd 복지업무비서
```

가상환경 생성 및 의존성 설치:

```powershell
python -m venv .venv-openkb
.\.venv-openkb\Scripts\python.exe -m pip install --upgrade pip
.\.venv-openkb\Scripts\python.exe -m pip install -r requirements.txt
```

`.venv-openkb`라는 이름은 과거 버전과의 경로 호환을 위해 유지한 디렉터리명일 뿐, 현재 환경에 OpenKB가 설치된다는 뜻은 아닙니다.

`requirements.txt`에는 직접 사용하는 패키지 외에, 취약점 스캐너가 실제 설치 버전을 정확히 인식하도록 전이 의존성 버전도 함께 고정되어 있습니다.

## 검색색인 생성·갱신

`source-md\`의 Markdown 원문을 SQLite 검색 DB로 다시 만들려면 다음을 실행합니다.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\setup-openkb.ps1 -RebuildIndex
```

현재 `setup-openkb.ps1`의 역할은 다음뿐입니다.

1. Python 가상환경 확인
2. 로컬 상태 디렉터리 초기화
3. `welfare_index.py build`를 이용한 SQLite 검색색인 생성
4. `welfare_assistant.py status` 상태 확인

**OpenKB 실행파일 검사, OpenKB 설치, OpenKB 네이티브 위키 생성은 수행하지 않습니다.**

파일명 `setup-openkb.ps1`은 기존 자동화와 경로 호환을 위해 유지합니다.

직접 명령으로 색인을 만들 수도 있습니다.

```powershell
.\.venv-openkb\Scripts\python.exe welfare_index.py build
.\.venv-openkb\Scripts\python.exe welfare_assistant.py status
```

`welfare_index.py build`는 검색 DB를 `wiki/kb-v120/`에 생성합니다. `setup-openkb.ps1`은 이 경로에 색인이 이미 있으면 재생성을 건너뛰고, `-RebuildIndex`를 지정하면 항상 다시 만듭니다.

## 개발 서버로 실행

EXE가 아닌 개발 상태에서 FastAPI 서버만 실행하려면:

```powershell
.\.venv-openkb\Scripts\python.exe welfare_web.py
```

접속 주소:

```text
http://127.0.0.1:8765/
```

이 방식은 개발·디버깅용입니다. 일반 사용자 배포 방식은 `복지업무비서.exe`입니다.

## 모델별 설치 패키지 빌드

패키징 전용 가상환경을 만듭니다.

```powershell
python -m venv .venv-package
.\.venv-package\Scripts\python.exe -m pip install --upgrade pip
.\.venv-package\Scripts\python.exe -m pip install -r requirements-build.txt
```

검색 DB가 준비된 상태에서 빌드:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\build-exe.ps1
```

또는 직접:

```powershell
.\.venv-package\Scripts\python.exe -m PyInstaller --noconfirm --clean .\welfare_assistant.spec
```

결과 파일:

```text
dist\복지톡AI_Setup_v1.3.4_E2B.exe
dist\복지톡AI_Setup_v1.3.4_E4B.exe
dist\복지톡AI_Setup_v1.3.4_E4B-*.bin
```

PyInstaller onedir 빌드에 웹 화면과 DB를 포함한 뒤, 해당 모델과 llama.cpp를 Inno Setup으로 묶습니다. 실행 파일 이름은 `복지업무비서_v{VERSION}_{E2B 또는 E4B}.exe`입니다. E4B 설치 EXE와 해당 `.bin` 파일을 하나의 ZIP으로 묶어 배포합니다.

## 테스트와 코드 검사

```powershell
.\.venv-package\Scripts\python.exe -m pytest -q
.\.venv-package\Scripts\python.exe -m ruff check welfare_*.py welfare_search tests
```

현재 검증 기준은 **39개 테스트 통과**이며, 이 중 1건은 원문 62.1MB 전체를 다시 색인하는 무거운 회귀 테스트라 다른 테스트보다 오래 걸립니다.

## 자료 갱신 절차

1. `source-md\`에서 Markdown 원문을 추가·교체합니다.
2. 검색색인을 다시 생성합니다.
3. 문서 수, 검색 구간 수, 원문 바이트 수를 확인합니다.
4. 실제 질문으로 검색·답변을 검증합니다.
5. `build-exe.ps1`로 새 EXE를 생성합니다.
6. 새 EXE에서 프로그램 창, AI 상태 표시, 질의, 종료까지 E2E 검증합니다.

기존 배포본과 원문이 완전히 같은지 확인할 때만 `verify-sources.ps1`을 사용합니다. 원문을 갱신한 뒤에는 과거 배포본 기준의 해시 검증 결과를 그대로 사용하면 안 됩니다.

## 주요 파일

| 파일/폴더 | 역할 |
| --- | --- |
| `welfare_launcher.py` | 단일 EXE 진입점, 로컬 서버 및 WebView 프로그램 창 관리 |
| `welfare_web.py` | FastAPI API 및 정적 웹 UI 제공 |
| `welfare_assistant.py` | 검색 근거 구성 및 LLM 호출 오케스트레이션 |
| welfare_llm.py | llama-server 프로세스 관리, GGUF 탐색, OpenAI 호환 API 호출 |
| welfare_models.py | 모델 선택지 상태 표시 |
| `welfare_runtime.py` | 리소스 경로 및 http/https로 제한된 내부 HTTP 통신 헬퍼 |
| `welfare_index.py` | SQLite 검색색인 생성 |
| `welfare_search/` | 검색 로직 |
| `web/` | 프로그램 UI |
| `source-md/` | 복지 업무 원문 Markdown |
| `setup-openkb.ps1` | 레거시 파일명을 유지한 검색 DB 초기화/재생성 스크립트 |
| `welfare_assistant.spec` | PyInstaller onedir 빌드 설정 |
| uild-exe.ps1 | PyInstaller 빌드 + runtime/models 스테이징 + Inno Setup 설치 파일 생성 |
| installer.iss | Inno Setup 설치 스크립트 |
| `tools/generate_bokjitalk_icon.ps1` | 원본 아이콘 PNG로부터 웹/EXE용 아이콘 자산을 생성하는 스크립트 |
| `requirements.txt` | 실행/개발 Python 의존성 (전이 의존성 버전 고정 포함) |
| `requirements-build.txt` | PyInstaller 빌드 의존성 (전이 의존성 버전 고정 포함) |

## 자주 겪는 문제

| 증상 | 확인할 사항 |
| --- | --- |
| `AI 엔진: 오류` | 설치 폴더 `logs\llama-server.log` 확인. 모델 파일 누락이면 재설치, 메모리 부족이면 다른 프로그램 종료 |
| E2B가 `미사용` | `models\gemma4-e2b-it-qat.gguf` 존재 여부 확인, 없으면 설치 파일 재실행 |
| 프로그램 창이 열리지 않음 | Microsoft Edge WebView2 Runtime 설치 상태 확인 |
| `포트 8765을 다른 프로그램이 사용 중입니다` | 기존 복지업무 비서 또는 다른 로컬 서버 종료 |
| 프로그램이 이미 실행 중이라는 메시지 | 기존 프로그램 창을 사용하거나 기존 인스턴스를 종료 |
| 개발용 `setup-openkb.ps1`에서 Python 오류 | `.venv-openkb` 생성 및 `requirements.txt` 설치 여부 확인 |
| 검색 DB가 없다는 빌드 오류 | 먼저 `welfare_index.py build`로 `wiki/kb-v120/welfare.db`를 생성했는지 확인 |

## 답변 원칙

- 검색된 복지DB 원문만 근거로 답변합니다.
- 원문에서 확인되지 않는 내용은 추측하지 않도록 프롬프트를 구성합니다.
- 핵심 결론, 요약, 상세 내용, 근거 지침, 확인 필요사항을 구조화해 표시합니다.
- 특정 연도 질문이 아니면 최신·현행 자료와 `authority=primary` 자료를 우선합니다.
- 서로 다른 연도의 수치·기준은 하나의 현행 기준으로 혼합하지 않습니다.
- 사례형 질문에서 최종 판단 조건이 부족하면 필요한 항목만 추가 확인 체크리스트로 표시합니다.
- 실제 수급 결정이나 행정처분은 담당자가 원문을 최종 확인해야 합니다.

## 라이선스

현재 저장소에는 별도의 오픈소스 라이선스가 지정돼 있지 않습니다. 개인용 설치와 사용 범위를 넘어 코드나 복지DB를 수정·재배포하려면 저장소 관리자에게 사용 조건을 확인해야 합니다.

복지 원문 자료의 저작권과 이용 조건은 각 발행기관의 기준을 따릅니다.
