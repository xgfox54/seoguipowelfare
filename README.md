![서귀포시 복지톡 AI 배너](docs/banner.png)

# 개인용 복지업무 비서

복지 업무자료 38개를 **로컬 SQLite FTS 검색색인**으로 검색하고, PC에 설치된 **Ollama + Gemma 4**가 검색된 원문만 근거로 답변하는 Windows용 개인 업무 도구입니다.

현재 배포 구조의 핵심은 **단일 EXE**입니다. `복지업무비서.exe`를 실행하면 기본 브라우저가 아니라 별도의 Windows 프로그램 창이 열리며, 내부 FastAPI 서버와 검색 DB, 웹 화면은 EXE에 함께 포함됩니다.

OpenAI API, ChatGPT Plus, OpenKB, OpenAI Agents SDK는 실행에 필요하지 않습니다.

(다운로드 페이지 링크)
https://gitlab.aigov.go.kr/memory365/seoguipowelfare/-/releases

## 현재 버전 한눈에 보기

| 항목 | 현재 구현 |
| --- | --- |
| 사용자 실행 파일 | `복지업무비서.exe` 단일 파일 |
| 화면 | pywebview + Microsoft Edge WebView2 기반 독립 프로그램 창 |
| 로컬 서버 | FastAPI / Uvicorn, `127.0.0.1:8765`에만 바인딩 |
| 검색 | SQLite FTS5/BM25 + 선택적 로컬 semantic hybrid 검색 |
| 복지 업무자료 | 38개 Markdown 원문 |
| 검색 구간 | 18,649개 |
| 원문 총량 | 61,234,862바이트 |
| 기본 AI 모델 | Gemma 4 E4B (`gemma4:e4b`) |
| 선택 가능 모델 | Gemma 4 E4B / Gemma 4 E2B QAT (`gemma4:e2b-it-qat`) |
| AI 호출 방식 | Ollama 로컬 HTTP API 직접 호출 |
| 인터넷 필요 여부 | 모델 최초 설치 시 필요, 일반 질의는 로컬 처리 |

## 일반 사용자: EXE로 실행하기

### 1. 필요한 프로그램

일반 사용자는 Python, Git, 가상환경을 설치할 필요가 없습니다. 다음 두 가지만 준비하면 됩니다.

1. **Windows 10/11**
2. **Ollama**

Ollama 설치:

- <https://ollama.com/download>

프로그램 창은 Microsoft Edge WebView2 런타임을 사용합니다. Windows 11과 최신 Windows 10 환경에는 보통 이미 설치돼 있습니다.

### 2. Gemma 모델 설치

PowerShell 또는 CMD에서 필요한 모델을 설치합니다.

```powershell
ollama pull gemma4:e4b
ollama pull gemma4:e2b-it-qat
```

두 모델을 모두 설치할 필요는 없습니다. 저장공간이나 PC 성능에 따라 하나만 설치해도 되며, 설치된 모델만 프로그램에서 사용할 수 있습니다.

설치 상태 확인:

```powershell
ollama list
```

### 3. `복지업무비서.exe` 실행

배포받은 `복지업무비서.exe`를 더블클릭합니다.

실행하면 다음 과정이 자동으로 진행됩니다.

1. 이미 프로그램이 실행 중인지 확인합니다.
2. `127.0.0.1:8765` 포트 사용 여부를 확인합니다.
3. Ollama가 꺼져 있고 `ollama` 명령을 찾을 수 있으면 `ollama serve` 시작을 시도합니다.
4. EXE 내부의 복지 검색 DB와 FastAPI 서버를 시작합니다.
5. 별도의 **개인용 복지업무 비서** 프로그램 창을 엽니다.

기본 브라우저를 자동으로 열지 않습니다.

### 4. 화면에서 AI 상태 확인

시스템 상태 영역에서 다음 항목을 바로 확인할 수 있습니다.

- **AI 연결**: 사용 가능한 Gemma 모델이 하나 이상 있으면 `연결됨`
- **Gemma 4 E4B**: `설치됨` / `미설치`
- **Gemma 4 E2B**: `설치됨` / `미설치`
- 복지 매뉴얼 수
- 검색 구간 수
- 현재 선택 모델

`시스템 정상`은 복지 원문과 검색색인이 정상이라는 뜻입니다. 실제 AI 답변을 생성하려면 Ollama가 실행 중이고 E4B 또는 E2B 모델이 하나 이상 설치돼 있어야 합니다.

### 5. 프로그램 종료

다음 두 방법 모두 내부 로컬 서버까지 함께 종료합니다.

- 프로그램 창 닫기
- 화면 오른쪽 위 **프로그램 종료** 버튼 누르기

프로그램 창만 사라지고 서버가 계속 남아 있는 브라우저 기반 실행 방식은 현재 기본 배포 방식이 아닙니다.

## 사용 방법

1. 질문란에 확인할 복지업무 내용을 입력합니다.
2. 사용할 모델을 선택합니다.
3. `질문하기`를 누르거나 Enter를 누릅니다.
4. 검색된 복지DB 원문을 근거로 생성된 답변을 확인합니다.
5. 중요한 안내, 급여 결정, 행정처분 전에는 반드시 원문 지침을 다시 확인합니다.

질문에는 주민등록번호, 전화번호, 상세 주소, 실명 등 개인 식별 정보를 입력하지 마십시오.

## 답변 처리 구조

현재 버전의 실제 처리 흐름은 다음과 같습니다.

```text
사용자 질문
   ↓
SQLite FTS 전체 원문 검색
   ↓
관련 복지 지침 구간 추출
   ↓
근거 포함 프롬프트 구성
   ↓
Ollama /api/generate 직접 호출
   ↓
Gemma 4 E4B 또는 E2B 답변 생성
   ↓
프로그램 창에 Markdown 렌더링
```

### OpenKB 사용 여부

현재 실행 경로에서는 **OpenKB를 사용하지 않습니다.**

과거 버전에서 사용하던 `.openkb` 디렉터리명과 `setup-openkb.ps1` 파일명 일부는 기존 작업환경 및 스크립트 호환을 위해 남아 있지만, 현재 `requirements.txt`에는 OpenKB가 포함돼 있지 않으며 실행 시 `openkb.exe`도 필요하지 않습니다.

AI 답변은 `welfare_assistant.py`가 Ollama의 로컬 HTTP API를 직접 호출해 생성합니다.

## 모델

### Gemma 4 E4B

- Ollama 태그: `gemma4:e4b`
- 프로그램 모델 키: `gemma_e4b`
- 현재 기본 모델

### Gemma 4 E2B QAT

- Ollama 태그: `gemma4:e2b-it-qat`
- 프로그램 모델 키: `gemma_e2b`
- 저사양 PC에서 선택 가능한 경량 모델

두 모델 모두 로컬 Ollama에서 실행되며 별도의 OpenAI API 요금은 발생하지 않습니다. 처리 속도와 답변 품질은 CPU, RAM, GPU, 모델 로딩 상태에 따라 달라집니다.

## 로컬 보안 구조

- FastAPI 서버는 `127.0.0.1`에만 바인딩됩니다.
- 웹 UI의 외부 폰트, 외부 스크립트, 통계/분석 서비스 의존성이 없습니다.
- Markdown 렌더링 시 원시 HTML은 비활성화합니다.
- 질문과 검색 원문은 Ollama 로컬 API로 전달됩니다.
- 프로그램 자체는 답변 생성을 위해 외부 AI API를 호출하지 않습니다.

단, Ollama 모델을 최초 다운로드하거나 Git 저장소/패키지를 설치하는 개발 과정에서는 인터넷 연결이 필요합니다.

## 복지DB 기준

현재 v1.2.0 검증 기준:

- 원문 문서: **38개**
- 원문 총량: **61,234,862바이트**
- 검색 구간: **18,649개**
- 검색 인덱스 DB: **약 266.9MB**
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
- Ollama

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

## 단일 EXE 빌드

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
.\.venv-package\Scripts\python.exe -m PyInstaller --noconfirm --clean .\복지업무비서.spec
```

결과 파일:

```text
dist\복지업무비서.exe
```

PyInstaller 설정은 `console=False`인 Windows 단일 EXE이며, `pywebview`와 `uvicorn` 모듈 및 검색 DB/웹 자원을 함께 패키징합니다.

## 테스트와 코드 검사

```powershell
.\.venv-openkb\Scripts\python.exe -m pytest -q
.\.venv-openkb\Scripts\python.exe -m ruff check welfare_*.py welfare_search tests
```

현재 검증 기준은 **25개 테스트 통과**입니다.

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
| `welfare_assistant.py` | 검색 근거 구성 및 Ollama 직접 호출 |
| `welfare_models.py` | Gemma 모델 정의 및 Ollama 설치 상태 확인 |
| `welfare_index.py` | SQLite 검색색인 생성 |
| `welfare_search/` | 검색 로직 |
| `web/` | 프로그램 UI |
| `source-md/` | 복지 업무 원문 Markdown |
| `setup-openkb.ps1` | 레거시 파일명을 유지한 검색 DB 초기화/재생성 스크립트 |
| `복지업무비서.spec` | PyInstaller 단일 EXE 설정 |
| `build-exe.ps1` | 단일 EXE 빌드 스크립트 |
| `requirements.txt` | 실행/개발 Python 의존성 |
| `requirements-build.txt` | PyInstaller 빌드 의존성 |

## 자주 겪는 문제

| 증상 | 확인할 사항 |
| --- | --- |
| `AI 연결: 연결 안 됨` | Ollama 실행 여부와 `ollama list` 확인 |
| E4B 또는 E2B가 `미설치` | 해당 `ollama pull ...` 명령 실행 |
| 프로그램 창이 열리지 않음 | Microsoft Edge WebView2 Runtime 설치 상태 확인 |
| `포트 8765을 다른 프로그램이 사용 중입니다` | 기존 복지업무 비서 또는 다른 로컬 서버 종료 |
| 프로그램이 이미 실행 중이라는 메시지 | 기존 프로그램 창을 사용하거나 기존 인스턴스를 종료 |
| 개발용 `setup-openkb.ps1`에서 Python 오류 | `.venv-openkb` 생성 및 `requirements.txt` 설치 여부 확인 |
| 검색 DB가 없다는 빌드 오류 | 먼저 `setup-openkb.ps1 -RebuildIndex` 또는 `welfare_index.py build` 실행 |

## 답변 원칙

- 검색된 복지DB 원문만 근거로 답변합니다.
- 원문에서 확인되지 않는 내용은 추측하지 않도록 프롬프트를 구성합니다.
- 핵심 결론, 요약, 상세 내용, 근거 지침, 확인 필요사항을 구조화해 표시합니다.
- 실제 수급 결정이나 행정처분은 담당자가 원문을 최종 확인해야 합니다.
- 상담 시 민원인의 개인 식별 정보를 입력하지 마십시오.

## 라이선스

현재 저장소에는 별도의 오픈소스 라이선스가 지정돼 있지 않습니다. 개인용 설치와 사용 범위를 넘어 코드나 복지DB를 수정·재배포하려면 저장소 관리자에게 사용 조건을 확인해야 합니다.

복지 원문 자료의 저작권과 이용 조건은 각 발행기관의 기준을 따릅니다.
