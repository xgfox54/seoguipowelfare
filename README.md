![서귀포시 복지톡 AI 배너](docs/banner.png)

# 개인용 복지업무 비서

복지톡에서 사용하던 38개 Markdown 업무자료를 자체 전체 원문 검색색인으로 검색하고, OpenKB의 질의 에이전트 구성요소와 로컬 Ollama(Gemma 4)를 이용해 답변하는 개인용 Windows 시스템입니다. 화면은 KRDS 설계 원칙을 참고해 색상, 타이포그래피, 반응형, 접근성을 구성했습니다.

질문과 원문이 전부 이 PC 안에서만 처리되며, 인터넷 연결 없이도 동작합니다(모델 설치는 최초 1회 인터넷이 필요합니다).

## 시작하기 전에 (준비물)

이 프로젝트는 **Windows 10/11과 Python 3.12에서 검증**했습니다. 아래 항목이 이 PC에 설치돼 있어야 하며, 이미 설치돼 있다면 건너뛰어도 됩니다. Python 3.13 이상은 현재 지원을 보장하지 않습니다.

| 준비물 | 확인 방법 | 설치 위치 |
| --- | --- | --- |
| Windows 10/11 | `winver` 실행 | PowerShell 및 CMD 실행 스크립트를 사용하므로 Windows가 필요합니다. |
| Python 3.12 | PowerShell에서 `python --version` | [python.org/downloads](https://www.python.org/downloads/) — 설치 화면에서 **"Add python.exe to PATH"를 반드시 체크** |
| Git | PowerShell에서 `git --version` | [git-scm.com/downloads](https://git-scm.com/downloads) |
| Ollama | PowerShell에서 `ollama --version` | [ollama.com/download](https://ollama.com/download) |

세 명령이 모두 버전 정보를 출력하면 준비 완료입니다.

## 1단계. 코드 내려받기

아무 폴더나 원하는 위치에서 PowerShell을 열고 다음을 실행합니다. (여기서는 예시로 문서 폴더 아래에 내려받습니다.)

```powershell
cd $HOME\Documents
git clone https://gitlab.aigov.go.kr/memory365/seoguipowelfare.git 복지업무비서
cd 복지업무비서
```

이후 안내되는 모든 명령은 이 `복지업무비서` 폴더 안에서 실행한다고 가정합니다. PowerShell 창을 새로 열었다면 먼저 `cd 복지업무비서를 내려받은 경로`로 이동하세요.

## 2단계. 실행환경(가상환경) 만들고 필요한 패키지 설치

아래 명령을 순서대로 하나씩 실행합니다. 패키지 설치는 자료 양이 많아 수 분 정도 걸릴 수 있습니다.

```powershell
python -m venv .venv-openkb
.\.venv-openkb\Scripts\python.exe -m pip install --upgrade pip
.\.venv-openkb\Scripts\python.exe -m pip install -r requirements.txt
```

마지막 줄이 오류 없이 끝나면 실행환경 준비가 끝난 것입니다.

## 3단계. 복지 업무자료 검색색인 만들기

`source-md\` 폴더 안의 38개 원문을 SQLite 기반 전체 원문 검색색인으로 변환합니다. 이 과정에서 OpenKB 질의 에이전트가 사용할 로컬 설정과 복지업무 정책 파일도 자동으로 준비합니다. 문서 용량이 커서 1~2분 정도 걸릴 수 있습니다.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\setup-openkb.ps1 -RebuildIndex
```

`Setup check completed.` 문구가 보이면 색인 생성이 끝난 것입니다.

## 4단계. 로컬 AI 모델 준비 (Ollama)

답변을 생성하는 AI 모델을 내려받습니다. 최초 1회만 인터넷이 필요하며, 이후에는 완전히 오프라인으로 동작합니다.

```powershell
ollama pull gemma4:e4b
ollama pull gemma4:e2b-it-qat
```

Ollama는 설치 시 백그라운드 서비스로 자동 등록되는 경우가 많습니다. 혹시 모델 다운로드 시 오류가 나면 Ollama 프로그램이 실행 중인지 먼저 확인하세요.

## 5단계. 실행하기

여기까지 마쳤다면 준비는 끝났습니다. `복지업무비서` 폴더에서 `복지업무비서.cmd`를 더블클릭합니다. 잠시 후 기본 브라우저에서 아래 주소가 자동으로 열립니다.

```text
http://127.0.0.1:8765/
```

브라우저를 닫아도 로컬 서버는 계속 실행됩니다. 완전히 종료하려면 `복지업무비서-종료.cmd`를 더블클릭합니다. 기존 명령창 방식이 필요하면 `복지업무비서-콘솔.cmd`를 사용합니다.

PowerShell에서 브라우저를 열지 않고 서버만 시작:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\복지업무비서-웹.ps1 -NoOpen
```

상태 확인:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\복지업무비서.ps1 -Status
```

정상 상태의 핵심 수치는 다음과 같습니다.

- 실행 방식: `로컬 Ollama` (인터넷 연결 불필요)
- 기본 모델: `ollama/gemma4:e4b`
- 전체 원문: 38개, 61,234,862바이트
- 전체 검색색인: 3,116개 근거 구간

화면의 `시스템 정상`은 **원문과 검색색인이 정상적으로 준비됐다는 뜻**입니다. Ollama 실행 여부와 모델 설치 여부는 별도로 확인하며, 설치되지 않은 모델은 선택 화면에서 `사용 불가`로 표시됩니다. 따라서 상단 상태가 정상이더라도 사용 가능한 로컬 모델이 하나 이상 있어야 실제 답변을 생성할 수 있습니다.

### 자주 겪는 문제

| 증상 | 원인과 해결 |
| --- | --- |
| `복지업무 비서 실행환경이 없습니다. setup-openkb.ps1을 먼저 실행하세요.` | 2단계(가상환경 생성)를 건너뛴 경우입니다. 2단계부터 다시 진행하세요. |
| `검증된 OpenKB 실행환경이 없습니다. Python 3.12로 .venv-openkb를 먼저 구성해야 합니다.` | `requirements.txt` 설치가 실패했거나 가상환경 구성이 중간에 중단된 경우입니다. 2단계 명령을 다시 실행하세요. |
| 화면은 열리는데 답변이 안 나옴 | Ollama가 실행 중인지, 4단계의 두 모델이 정상적으로 받아졌는지 확인하세요(`ollama list`로 확인 가능). |
| `python`, `git`, `ollama` 명령을 찾을 수 없음 | 설치 후 PowerShell 창을 새로 열지 않았을 수 있습니다. 창을 닫았다가 다시 열어보세요. |

## 사용 방법

1. 질문란에 대상자의 상황과 확인할 업무를 적습니다.
2. `질문하기`를 누르거나 Enter를 누릅니다. 줄바꿈은 Shift+Enter를 사용합니다.
3. 답변의 결론, 적용 조건·예외, 실무 확인사항을 읽습니다.
4. 중요한 안내나 처분 전에는 표시된 문서명과 원문 줄을 다시 확인합니다.

주민등록번호, 주소, 전화번호, 실명 등 개인정보는 질문에 입력하지 마십시오. 답변은 로컬 Ollama에서 생성되므로 질문과 원문은 외부로 전송되지 않습니다.

답변 모델은 화면에서 **Gemma 4 E4B**와 **Gemma 4 E2B QAT Q4** 중 선택할 수 있습니다. 두 모델 모두 로컬 Ollama에서 실행되므로 질문이 이 PC를 벗어나지 않습니다.

## 시스템 구성

질문은 다음 순서로 처리합니다.

1. 전체 원문 검색색인: 38개 대용량 Markdown에서 질문과 관련된 구간을 검색하고 문서명과 원문 줄 범위를 추출합니다.
2. OpenKB 질의 에이전트 구성요소: 로컬 모델 연결, 실행 설정과 복지업무 답변 정책을 적용합니다.
3. 로컬 Ollama: 검색된 원문만 근거로 답변을 생성합니다.

현재 배포본은 38개 문서를 OpenKB 네이티브 위키로 컴파일하거나 네이티브 위키 검색 도구로 조회하지 않습니다. 대용량 합본 문서를 로컬 모델의 문맥 한도 안에서 안정적으로 다루기 위해 자체 검색색인을 사용하며, 일상 질문의 검색 범위는 항상 전체 38개 원문입니다.

## 사용 모델과 실행 환경

이 프로젝트는 OpenAI API 키나 ChatGPT Plus 계정 없이 동작합니다. 답변은 로컬에 설치된 Ollama가 처리하며, 두 모델(`ollama/gemma4:e4b`, `ollama/gemma4:e2b-it-qat`)을 호출할 때 별도의 API 사용 요금이 발생하지 않습니다. 모델 이용 조건은 각 모델의 라이선스를 따르며, 처리 속도와 답변 품질은 이 PC의 메모리·CPU·GPU 성능에 좌우됩니다.

Ollama가 실행 중이어야 하며(`ollama serve`, 보통 설치 시 자동 등록됨), 4단계에서 받은 두 모델이 설치돼 있어야 화면에서 선택할 수 있습니다.

모델 설치 용량과 현재 사용 가능 여부는 다음 명령으로 확인할 수 있습니다.

```powershell
ollama list
```

PC 사양이나 저장공간이 부족하면 두 모델을 모두 설치할 필요는 없습니다. 설치된 모델만 선택할 수 있습니다.

## 자료 갱신

`source-md\`에 새 버전의 Markdown을 추가하거나 기존 파일을 교체한 뒤 다음을 실행합니다.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\setup-openkb.ps1 -RebuildIndex
```

문서 수, 전체 바이트 수와 검색 구간 수는 자료가 바뀌면 함께 달라질 수 있습니다. 갱신 후에는 `-Status` 명령과 실제 질문으로 새 자료가 검색되는지 확인하세요.

현재 `v1.0.2` 배포본의 38개 파일이 기존 다운로드 폴더 사본과 완전히 같은지 확인할 때만 다음 명령을 사용합니다.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\verify-sources.ps1
```

`verify-sources.ps1`은 다운로드 폴더 아래에서 **38개·61,234,862바이트인 원본 폴더가 정확히 하나 존재한다는 전제**로 SHA-256을 비교합니다. 새 매뉴얼로 교체한 뒤에는 이전 배포본 기준의 이 명령을 사용하지 마세요.

## 개발 및 검증

가상환경과 검색색인이 준비된 상태에서 다음 명령으로 코드와 검색 재현성을 확인할 수 있습니다.

```powershell
.\.venv-openkb\Scripts\python.exe -m ruff check welfare_*.py welfare_search tests
.\.venv-openkb\Scripts\python.exe -m pytest -q
```

GitLab의 `verify_on_runner` 작업은 Runner가 연결된 환경에서 수동으로 실행하는 선택형 검증 작업입니다. Runner가 할당되지 않은 현재 환경에서는 파이프라인이 실패하지 않고 `skipped`로 표시되는 것이 정상입니다.

## 답변 원칙

- 질문에 기준연도를 포함하면 해당 연도 세부 사업안내를 우선합니다.
- 수치·자격·예외에는 문서명과 줄 범위를 표시합니다.
- 중앙부처 지침과 제주·서귀포 지역지침을 구분합니다.
- 종합안내서보다 해당 사업의 세부 안내서를 우선합니다.
- 자료에 없거나 문서끼리 충돌하면 추정하지 않고 그 사실을 표시합니다.
- 실제 수급 결정이나 행정처분은 담당자의 최종 확인이 필요합니다.

## 로컬 보안

- 서버는 외부 네트워크가 아닌 `127.0.0.1`에만 연결됩니다.
- 외부 폰트, 스크립트, 이미지, 통계 도구를 불러오지 않습니다.
- 모델 답변의 Markdown은 원시 HTML을 비활성화한 뒤 표시합니다.
- 디자인 시스템 규칙은 `DESIGN.md`, 컴포넌트 상태는 `http://127.0.0.1:8765/showcase`에서 확인할 수 있습니다.

## 다른 PC로 이식하기

`.venv-openkb`(가상환경)와 `wiki\search\welfare.db`(검색색인)는 이 저장소에 포함돼 있지 않습니다. 용량이 크고 각 PC에서 새로 만들 수 있기 때문입니다. 다른 PC에서 사용하려면 위의 **1~4단계**를 그대로 반복하면 됩니다.

설치 스크립트는 기존 `.openkb\config.yaml`을 덮어쓰지 않으므로, 재설치하거나 색인을 갱신해도 사용자가 선택한 로컬 설정은 유지됩니다.

```powershell
cd $HOME\Documents
git clone https://gitlab.aigov.go.kr/memory365/seoguipowelfare.git 복지업무비서
cd 복지업무비서
python -m venv .venv-openkb
.\.venv-openkb\Scripts\python.exe -m pip install --upgrade pip
.\.venv-openkb\Scripts\python.exe -m pip install -r requirements.txt
powershell.exe -ExecutionPolicy Bypass -File .\setup-openkb.ps1 -RebuildIndex
ollama pull gemma4:e4b
ollama pull gemma4:e2b-it-qat
```

로컬 Gemma 모델은 PC마다 별도로 설치해야 합니다. 설치하지 않은 모델은 상태 화면에서 "사용 불가"로 표시됩니다.

## 라이선스

현재 저장소에는 별도의 오픈소스 라이선스가 지정돼 있지 않습니다. 개인용 설치와 사용 범위를 넘어 코드나 복지DB를 수정·재배포하려면 저장소 관리자에게 사용 조건을 확인해야 합니다. 원문 복지 매뉴얼의 저작권과 이용 조건은 각 발행기관의 기준을 따릅니다.
