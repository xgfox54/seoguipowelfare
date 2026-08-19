# 개인용 복지업무 비서

복지톡에서 사용하던 38개 Markdown 업무자료를 OpenKB와 로컬 Ollama(Gemma 4)로 질의하는 개인용 로컬 시스템입니다. 화면은 KRDS-MCP의 색상, 타이포그래피, 반응형, 접근성 원칙을 적용했습니다.

## 바로 사용하기

`C:\Users\USER\Documents\Codex\복지업무비서\복지업무비서.cmd`를 더블클릭합니다. 잠시 후 기본 브라우저에서 아래 주소가 열립니다.

```text
http://127.0.0.1:8765/
```

브라우저를 닫아도 로컬 서버는 계속 실행됩니다. 완전히 종료하려면 `복지업무비서-종료.cmd`를 더블클릭합니다. 기존 명령창 방식이 필요하면 `복지업무비서-콘솔.cmd`를 사용합니다.

PowerShell에서 브라우저를 열지 않고 서버만 시작:

```powershell
Set-Location 'C:\Users\USER\Documents\Codex\복지업무비서'
powershell.exe -ExecutionPolicy Bypass -File .\복지업무비서-웹.ps1 -NoOpen
```

상태 확인:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\복지업무비서.ps1 -Status
```

정상 상태의 핵심 수치는 다음과 같습니다.

- 인증: `로컬 Ollama` (인터넷 연결 불필요)
- 기본 모델: `ollama/gemma4:e4b`
- 전체 원문: 38개, 61,234,862바이트
- 전체 검색색인: 3,116개 근거 구간
- OpenKB 네이티브 컴파일: 현재 등록 수는 화면의 시스템 상태에서 확인

## 사용 방법

1. 질문란에 대상자의 상황과 확인할 업무를 적습니다.
2. `복지DB에서 찾기`를 누릅니다.
3. 답변의 결론, 적용 조건·예외, 실무 확인사항을 읽습니다.
4. 중요한 안내나 처분 전에는 표시된 문서명과 원문 줄을 다시 확인합니다.

주민등록번호, 주소, 전화번호, 실명 등 개인정보는 질문에 입력하지 마십시오. 답변은 로컬 Ollama에서 생성되므로 질문과 원문은 외부로 전송되지 않습니다.

답변 모델은 화면에서 **Gemma 4 E4B**와 **Gemma 4 E2B QAT Q4** 중 선택할 수 있습니다. 두 모델 모두 로컬 Ollama에서 실행되므로 질문이 이 PC를 벗어나지 않습니다.

## 시스템 구성

전체 자료는 다음 두 층으로 사용합니다.

1. OpenKB 네이티브 위키: 표본 문서를 요약·개념·엔티티로 컴파일해 설치와 질의 동작을 검증합니다.
2. 전체 원문 검색색인: 38개 대용량 Markdown을 빠르게 검색하고, 질문과 관련된 원문 및 줄 번호를 로컬 모델에 전달합니다.

이 하이브리드 구조를 사용한 이유는 현재 OpenKB가 Markdown 파일을 페이지 수 기준의 장문 문서로 분류하지 않고 문서 전체를 한 번에 모델에 보내기 때문입니다. 수 MB짜리 합본 38개를 전부 네이티브 컴파일하면 로컬 모델의 문맥 한도를 크게 초과할 수 있습니다. 일상 질문은 전체 38개 원문을 모두 검색하므로 네이티브 컴파일 수와 관계없이 자료 검색 범위는 38개입니다.

## 사용 모델과 실행 환경

이 프로젝트는 OpenAI API 키나 ChatGPT Plus 계정 없이 동작합니다. 답변은 로컬에 설치된 Ollama가 처리하며, 두 모델(`ollama/gemma4:e4b`, `ollama/gemma4:e2b-it-qat`) 모두 무료이고 추가 사용 요금이 없습니다. 대신 처리 속도와 답변 품질은 이 PC의 하드웨어 성능에 좌우됩니다.

Ollama가 실행 중이어야 하며(`ollama serve`, 보통 설치 시 자동 등록됨), 아래 모델이 설치돼 있어야 화면에서 선택할 수 있습니다.

```powershell
ollama pull gemma4:e4b
ollama pull gemma4:e2b-it-qat
```

## 자료 갱신

`source-md\`에 새 버전의 Markdown을 추가하거나 기존 파일을 교체한 뒤 다음을 실행합니다.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\setup-openkb.ps1 -RebuildIndex
```

원본 38개가 다운로드 폴더 사본과 같은지 확인:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\verify-sources.ps1
```

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

## 다른 노트북으로 이식하기

지금 PC에서 압축을 만듭니다. `.venv`, `.venv-openkb`는 용량이 커서 압축에서 제외됩니다.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\package-for-laptop.ps1
```

바탕화면에 `복지업무비서-이식.zip`이 생성됩니다. 이 파일을 USB나 클라우드로 노트북에 옮깁니다.

노트북에서 압축을 원하는 위치(예: `C:\Users\사용자\Documents\Codex\복지업무비서`)에 풉니다. Python이 없다면 [python.org](https://www.python.org/downloads/)에서 **3.12** 버전을 먼저 설치합니다(설치 중 "Add python.exe to PATH" 체크). 그다음 압축을 푼 폴더에서 실행합니다.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\install-on-new-pc.ps1
```

이 스크립트가 `.venv-openkb`를 새로 만들고, `requirements.txt`의 패키지를 설치하고, 복지DB 검색색인을 구축합니다. 완료 후 `복지업무비서.cmd`를 실행하면 됩니다.

로컬 Gemma 모델은 PC마다 별도로 설치해야 합니다. 노트북에도 Ollama를 설치하고 아래 두 모델을 받아야 화면에서 선택할 수 있습니다.

```powershell
ollama pull gemma4:e4b
ollama pull gemma4:e2b-it-qat
```

설치하지 않은 모델은 상태 화면에서 "사용 불가"로 표시됩니다.
