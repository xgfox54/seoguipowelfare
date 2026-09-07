# v1.3.2 — Ollama 제거, llama.cpp 내장 올인원 설치 패키지

## 목적

Ollama 없이, 인터넷 없이, 설치 파일 하나만으로 실행되는 복지톡 AI를 만드는 것이 목표입니다. 이번 버전부터 AI 엔진(llama.cpp)과 Gemma 4 모델이 설치 패키지에 포함됩니다.

## 구조 비교

| 구분 | v1.3.1 이전 | v1.3.2 |
| --- | --- | --- |
| LLM 런타임 | 사용자가 직접 설치한 Ollama (`127.0.0.1:11434`) | 내장 `runtime\llamacpp\llama-server.exe` (`127.0.0.1:18080`) |
| 모델 | `ollama pull gemma4:e4b` 등 사용자가 직접 다운로드 | `models\gemma4-e2b-it-qat.gguf` 설치 파일에 포함 |
| 배포물 | 단일 onefile EXE (모델 미포함) | `복지톡AI_Setup_v1.3.2.exe` 설치 파일 (약 3.3GB, 모델 포함) |
| 사용자 준비 | Ollama 설치, 모델 pull, 명령 프롬프트 | 없음 |
| 검색·RAG·UI | 유지 | 유지 |

## 제거된 Ollama 의존성

- `welfare_models.py`: `find_ollama_executable`, `ollama_is_running`, `installed_local_models`, `OLLAMA_BASE_URL`, `OLLAMA_WINDOWS_DOWNLOAD_URL`
- `welfare_assistant.py`: `_ollama_generate` → `welfare_llm.generate` (OpenAI 호환 `/v1/chat/completions`)
- `welfare_launcher.py`: `_try_start_ollama`, `_ollama_is_running`, `open_ollama_download`
- `welfare_search/semantic.py`: 임베딩 엔드포인트를 `/api/embed` → `/v1/embeddings`로 변경 (임베딩 모델 미탑재 시 기존대로 FTS 폴백)
- `web/`: Ollama 설치 안내 다이얼로그, 다운로드 버튼, `ollama pull` 명령 복사 UI 제거
- API 응답: `ollama_installed`/`ollama_running` → `engine_state`/`engine_error`

## 새로 추가된 구성

- `welfare_llm.py`: llama-server 탐색·실행·readiness·종료를 담당하는 런타임 매니저와 LLM 호출 함수. Windows Job Object(KILL_ON_JOB_CLOSE)로 앱이 강제종료돼도 llama-server가 함께 정리됩니다.
- `installer.iss`: Inno Setup 스크립트. `%LOCALAPPDATA%\BokjiTalkAI`에 관리자 권한 없이 설치.
- `build-exe.ps1`: PyInstaller onedir 빌드 → runtime/models 스테이징 → Inno Setup 컴파일까지 한 번에 수행.
- UI: AI 엔진 상태(시작 중 / 모델 불러오는 중 / 실행 중 / 오류)와 오류 원인 표시, 준비 전 질문 버튼 비활성화.

## llama.cpp / 모델 정보

- llama.cpp: **b10834** (commit 992cb503c, Vulkan x64 Windows 빌드, 2026-09-07 릴리스)
- 모델: **Gemma 4 E2B QAT Q4**, 파일 `gemma4-e2b-it-qat.gguf`, 3,349,514,112바이트 (Ollama 배포 blob과 동일한 GGUF)
- 실행 옵션: `-c 16384 -t min(8, CPU-2) -np 1 -ngl 99(Vulkan DLL 있을 때) --jinja --no-webui`, `127.0.0.1` 바인딩
- Gemma 4 chat template은 `--jinja`로 적용하며 `enable_thinking=false`, `reasoning_format=none`으로 thinking 출력을 끕니다. (thinking을 켜면 `content`가 비고 `reasoning_content`만 채워지는 현상을 확인해 비활성화)

## 검증

- 단위/통합 테스트 38개 통과 (`pytest -k "not release_corpus"`), Ruff 통과
- 개발 환경 launcher: loading → ready 전이 약 10초, 기초연금 RAG 질문 3단계(정제·답변·감독) 80초, 근거 지침·형식 유지 확인
- 설치본 E2E: `복지톡AI_Setup_v1.3.2.exe` 조용히 설치 → `복지업무비서.exe` 실행 → 8초 내 ready → 긴급복지 질문 103초 답변 → `/api/shutdown` 종료
- 반복 실행 3회: 매회 ready 도달 후 강제종료, 잔여 `복지업무비서.exe`/`llama-server.exe` 0개 확인
- 강제종료(taskkill /F) 후 llama-server 자동 정리 확인 (Job Object)
- 성능(GTX 1660 Ti, Vulkan): 생성 약 26 tok/s, CPU-only 약 16 tok/s

## 설치 방법

1. 실행 중인 복지업무비서를 종료합니다. 기존 v1.3.1 이하 EXE는 삭제해도 됩니다.
2. `복지톡AI_Setup_v1.3.2.exe`를 실행하고 안내에 따라 설치합니다. 인터넷 연결이 필요 없습니다.
3. 시작 메뉴 또는 바탕화면의 **복지톡AI 복지업무비서**를 실행합니다. 첫 실행 시 모델 로딩에 10초~1분이 걸립니다.
4. Ollama가 설치되어 있어도 사용하지 않으므로 제거해도 됩니다.

## 남은 과제

- E4B 모델은 9.6GB라 설치 파일에 포함하지 않았습니다. 필요 시 `models\gemma4-e4b.gguf`를 수동 배치하면 자동 인식됩니다.
- 설치 파일은 코드 서명이 없어 SmartScreen 경고가 표시될 수 있습니다.
- GPU가 없는 PC에서는 CPU-only로 동작하며 답변 속도가 느려집니다(Vulkan DLL은 GPU가 없으면 자동으로 CPU 백엔드 사용).
- semantic 임베딩 기능은 임베딩용 GGUF를 별도로 서빙해야 하므로 현재 비활성(FTS 검색만 사용, 기존과 동일).
