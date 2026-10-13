from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from welfare_runtime import bundle_root, open_http_url

LLM_HOST = "127.0.0.1"
LLM_PORT = 18080  # 정식판 모델 서버 포트 (v1.4.0 정식판과 같음)
LLM_BASE_URL = f"http://{LLM_HOST}:{LLM_PORT}"
DEFAULT_CONTEXT_SIZE = 16384
STARTUP_TIMEOUT_SECONDS = 180

logger = logging.getLogger("welfare.llm")


def install_root() -> Path:
    frozen_root = os.environ.get("WELFARE_INSTALL_ROOT")
    if frozen_root:
        return Path(frozen_root)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return bundle_root()


def runtime_dir() -> Path:
    return install_root() / "runtime" / "llamacpp"


def models_dir() -> Path:
    return install_root() / "models"


def log_dir() -> Path:
    # A read-only model/runtime asset override must not redirect app logs.
    target = (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False)
              else bundle_root()) / "logs"
    target.mkdir(parents=True, exist_ok=True)
    return target


@dataclass(frozen=True, slots=True)
class GgufModel:
    key: str
    label: str
    filename: str
    description: str

    @property
    def path(self) -> Path:
        return models_dir() / self.filename

    @property
    def exists(self) -> bool:
        try:
            return self.path.is_file()
        except OSError:
            return False


MODEL_CHOICES: tuple[GgufModel, ...] = (
    GgufModel(
        key="gemma_e2b",
        label="Gemma 4 E2B QAT Q4",
        filename="gemma4-e2b-it-qat.gguf",
        description="빠르고 가벼운 모델입니다. 인터넷 연결 없이 동작합니다.",
    ),
    GgufModel(
        key="gemma_e4b",
        label="Gemma 4 E4B QAT Q4",
        filename="gemma4-e4b.gguf",
        description="더 정확하지만 무거운 모델입니다. 인터넷 연결 없이 동작합니다.",
    ),
)
_CHOICES_BY_KEY = {choice.key: choice for choice in MODEL_CHOICES}
MODEL_VARIANT_KEYS: Final[dict[str, str]] = {"E2B": "gemma_e2b", "E4B": "gemma_e4b"}


def configured_model_variant() -> str:
    """Return the model variant embedded in/assigned to this distribution.

    Packaged executables are renamed by build-exe.ps1 to include `_E2B` or
    `_E4B`, which gives the runtime a deterministic build identity without
    scanning the models directory. Environment variables are supported for
    development and automated tests.
    """
    for env_name in ("MODEL_VARIANT", "WELFARE_MODEL_VARIANT"):
        configured = os.environ.get(env_name, "").strip().upper()
        if configured in MODEL_VARIANT_KEYS:
            return configured
    executable_name = Path(sys.executable).name.upper()
    if "_E4B" in executable_name:
        return "E4B"
    if "_E2B" in executable_name:
        return "E2B"
    return "E2B"


DEFAULT_MODEL_KEY = MODEL_VARIANT_KEYS[configured_model_variant()]


def resolve_choice(model_key: str | None) -> GgufModel:
    if model_key is None:
        return _CHOICES_BY_KEY[DEFAULT_MODEL_KEY]
    choice = _CHOICES_BY_KEY.get(model_key)
    if choice is None:
        raise KeyError(model_key)
    return choice


def configured_model_choice() -> GgufModel:
    return _CHOICES_BY_KEY[MODEL_VARIANT_KEYS[configured_model_variant()]]


def select_model() -> GgufModel | None:
    choice = configured_model_choice()
    return choice if choice.exists else None


def find_llama_server() -> Path | None:
    candidate = runtime_dir() / "llama-server.exe"
    try:
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def server_is_ready(timeout: float = 1.5) -> bool:
    try:
        with open_http_url(f"{LLM_BASE_URL}/health", timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("status") == "ok"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def loaded_model_file() -> str:
    try:
        with open_http_url(f"{LLM_BASE_URL}/v1/models", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return ""
    entries = payload.get("data", [])
    if not entries:
        return ""
    return Path(str(entries[0].get("id", ""))).name


def _port_is_busy() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((LLM_HOST, LLM_PORT)) == 0


def _thread_count() -> int:
    logical = os.cpu_count() or 4
    return max(2, min(8, logical - 2))


def _kill_on_close_job() -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

    class JobLimit(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JobLimit),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    info = ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = 0x2000
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        return None
    return int(job)


def _assign_to_job(job: int | None, process: subprocess.Popen[bytes]) -> None:
    if job is None or sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.kernel32.AssignProcessToJobObject(job, int(process._handle))


class LlamaRuntime:

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._job = _kill_on_close_job()
        self.model: GgufModel | None = None
        self.error: str = ""
        self.state: str = "idle"
        self.gpu_layers: int = 0

    def start(self) -> None:
        with self._lock:
            expected_model = configured_model_choice()
            if not expected_model.exists:
                self.state = "error"
                self.model = None
                self.error = (
                    f"현재 {configured_model_variant()} 배포판에 필요한 AI 모델 파일 "
                    f"({expected_model.filename})을 찾을 수 없습니다. 다른 모델로 자동 대체하지 않습니다."
                )
                logger.error("required GGUF missing: variant=%s file=%s", configured_model_variant(), expected_model.filename)
                return
            if server_is_ready():
                loaded_filename = loaded_model_file()
                if loaded_filename != expected_model.filename:
                    self.state = "error"
                    self.model = None
                    self.error = (
                        "AI 엔진에 현재 배포판과 다른 모델이 로딩되어 있습니다. "
                        f"요청={expected_model.filename}, 로딩={loaded_filename or '확인불가'}"
                    )
                    logger.error("model mismatch on existing server: expected=%s loaded=%s", expected_model.filename, loaded_filename)
                    return
                self.state = "ready"
                self.model = expected_model
                return
            executable = find_llama_server()
            model = select_model()
            if executable is None:
                self.state = "error"
                self.error = "AI 엔진 파일(llama-server)을 찾을 수 없습니다. 설치가 정상적으로 완료되었는지 확인하십시오."
                logger.error("llama-server missing under %s", runtime_dir())
                return
            if model is None:
                self.state = "error"
                self.error = (
                    f"현재 {configured_model_variant()} 배포판에 필요한 AI 모델 파일 "
                    f"({expected_model.filename})을 찾을 수 없습니다. 다른 모델로 자동 대체하지 않습니다."
                )
                logger.error("required GGUF missing: variant=%s file=%s", configured_model_variant(), expected_model.filename)
                return
            if _port_is_busy():
                self.state = "error"
                self.error = f"AI 엔진 포트 {LLM_PORT}를 다른 프로그램이 사용 중입니다."
                return
            self.model = model
            self.state = "loading"
            self.gpu_layers = 99 if (runtime_dir() / "ggml-vulkan.dll").is_file() else 0
            args = [
                str(executable),
                "-m", str(model.path),
                "--host", LLM_HOST,
                "--port", str(LLM_PORT),
                "-c", str(DEFAULT_CONTEXT_SIZE),
                "-t", str(_thread_count()),
                "-np", "1",
                "-ngl", str(self.gpu_layers),
                "--jinja",
                "--no-webui",
                "--log-timestamps",
            ]
            stdout = (log_dir() / "llama-server.log").open("ab")
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32":
                creationflags |= getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
            logger.info("starting llama-server: model=%s size=%d gpu_layers=%d threads=%s", model.filename, model.path.stat().st_size, self.gpu_layers, _thread_count())
            try:
                self._process = subprocess.Popen(
                    args,
                    cwd=str(runtime_dir()),
                    stdout=stdout,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                _assign_to_job(self._job, self._process)
            except OSError:
                self.state = "error"
                self.error = "AI 엔진을 시작하지 못했습니다. 프로그램을 다시 실행해 주십시오."
                logger.exception("llama-server spawn failed")
                return
        started = time.monotonic()
        while time.monotonic() - started < STARTUP_TIMEOUT_SECONDS:
            if self._process is not None and self._process.poll() is not None:
                self.state = "error"
                self.error = self._diagnose_exit()
                return
            if server_is_ready():
                loaded_filename = loaded_model_file()
                if loaded_filename != model.filename:
                    mismatch_error = (
                        "AI 엔진이 현재 배포판과 다른 모델을 로딩했습니다. "
                        f"요청={model.filename}, 로딩={loaded_filename or '확인불가'}"
                    )
                    logger.error("model mismatch after startup: expected=%s loaded=%s", model.filename, loaded_filename)
                    self.stop()
                    self.state = "error"
                    self.error = mismatch_error
                    return
                self.state = "ready"
                logger.info("llama-server ready after %.1fs", time.monotonic() - started)
                return
            time.sleep(0.5)
        self.state = "error"
        self.error = "AI 모델 로딩 시간이 초과되었습니다. 메모리가 부족할 수 있습니다."
        self.stop()

    def _diagnose_exit(self) -> str:
        try:
            tail = (log_dir() / "llama-server.log").read_text(encoding="utf-8", errors="replace")[-4000:]
        except OSError:
            tail = ""
        lowered = tail.lower()
        if "out of memory" in lowered or "failed to allocate" in lowered or "cannot allocate" in lowered:
            return "AI 모델을 실행하기 위한 메모리가 부족할 수 있습니다."
        return "AI 엔진을 시작하지 못했습니다. 프로그램을 다시 실행해 주십시오."

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        logger.info("llama-server stopped (exit=%s)", process.returncode)
        self.state = "idle"


RUNTIME = LlamaRuntime()
GENERATION_SEED = 20260101
EMBEDDING_PORT = 18081
EMBEDDING_BASE_URL = f"http://{LLM_HOST}:{EMBEDDING_PORT}"
EMBEDDING_MODEL_FILENAME = "bge-m3-q8_0.gguf"
EMBEDDING_THREADS = 2


class EmbeddingRuntime:
    """Second llama-server that embeds questions for semantic retrieval.

    Optional: without its model file the app answers from lexical search only.
    It runs on the CPU so the answer model keeps the GPU.
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._job = _kill_on_close_job()
        self.state: str = "idle"

    @property
    def model_path(self) -> Path:
        return models_dir() / EMBEDDING_MODEL_FILENAME

    def _healthy(self) -> bool:
        try:
            with open_http_url(f"{EMBEDDING_BASE_URL}/health", timeout=1.5) as response:
                return response.status == 200 and json.loads(response.read().decode("utf-8")).get("status") == "ok"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return False

    def start(self) -> None:
        with self._lock:
            executable = find_llama_server()
            if executable is None or not self.model_path.is_file():
                self.state = "unavailable"
                return
            if self._healthy():
                self.state = "ready"
                return
            args = [
                str(executable),
                "-m", str(self.model_path),
                "--embedding",
                "--host", LLM_HOST,
                "--port", str(EMBEDDING_PORT),
                "-c", "2048",
                "-t", str(EMBEDDING_THREADS),
                "-np", "1",
                "-ngl", "0",
                "--no-webui",
                "--log-timestamps",
            ]
            stdout = (log_dir() / "embedding-server.log").open("ab")
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32":
                creationflags |= getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
            try:
                self._process = subprocess.Popen(
                    args, cwd=str(runtime_dir()), stdout=stdout, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, creationflags=creationflags,
                )
                _assign_to_job(self._job, self._process)
            except OSError:
                logger.exception("embedding server spawn failed")
                self.state = "error"
                return
            self.state = "loading"
        started = time.monotonic()
        while time.monotonic() - started < STARTUP_TIMEOUT_SECONDS:
            if self._process is not None and self._process.poll() is not None:
                logger.error("embedding server exited during startup (exit=%s)", self._process.returncode)
                self.state = "error"
                return
            if self._healthy():
                logger.info("embedding server ready after %.1fs", time.monotonic() - started)
                self.state = "ready"
                return
            time.sleep(0.5)
        self.state = "error"
        self.stop()

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.state = "idle"


EMBEDDING_RUNTIME = EmbeddingRuntime()


def generate(
    prompt: str,
    *,
    system_prompt: str,
    temperature: float = 0.0,
    timeout: int = 600,
    max_tokens: int = 2048,
    grammar: str | None = None,
) -> str:
    body: dict[str, object] = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "seed": GENERATION_SEED,
        "max_tokens": max_tokens,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_format": "none",
    }
    if grammar:
        # llama.cpp GBNF: constrains output structure only; facts are still
        # validated by welfare_grounding after generation.
        body["grammar"] = grammar
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    result: dict[str, object] | None = None
    last_connection_error: BaseException | None = None
    for attempt in range(2):
        request = urllib.request.Request(
            f"{LLM_BASE_URL}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with open_http_url(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            error.close()
            logger.error("llm http error %s (response body omitted)", error.code)
            raise RuntimeError(f"AI 엔진 응답 오류({error.code})") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_connection_error = error
            if attempt == 0:
                logger.warning("llama-server connection lost; attempting one automatic restart")
                RUNTIME.start()
                if RUNTIME.state == "ready":
                    continue
            raise RuntimeError("AI 엔진에 연결할 수 없습니다. 프로그램을 다시 실행해 주십시오.") from error
    if result is None:
        raise RuntimeError("AI 엔진에 연결할 수 없습니다. 프로그램을 다시 실행해 주십시오.") from last_connection_error
    choices = result.get("choices", [])
    from welfare_telemetry import note
    note('generation', {'finish_reason': choices[0].get('finish_reason') if choices else 'empty',
                        'truncated': bool(choices and choices[0].get('finish_reason') == 'length')})
    if not choices:
        return "답변을 생성하지 못했습니다."
    answer = str(choices[0].get("message", {}).get("content", "")).strip()
    return answer or "답변을 생성하지 못했습니다."
