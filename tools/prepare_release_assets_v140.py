from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache-release"
MODELS = ROOT / "models"
RUNTIME = ROOT / "runtime" / "llamacpp"
QUALITY = ROOT / "quality"

ASSETS = {
    "e2b": {
        "url": "https://huggingface.co/unsloth/gemma-4-E2B-it-qat-GGUF/resolve/main/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf?download=true",
        "cache": "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf",
        "dest": MODELS / "gemma4-e2b-it-qat.gguf",
        "sha256": "e531007218dfab990486a5de7676a6932d6ea8dea233d1f698d7c21cf8a16889",
    },
    "e4b": {
        "url": "https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf?download=true",
        "cache": "gemma-4-E4B-it-Q4_K_M.gguf",
        "dest": MODELS / "gemma4-e4b.gguf",
        "sha256": "85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87",
    },
    "llama": {
        "url": "https://github.com/ggml-org/llama.cpp/releases/download/b10686/llama-b10686-bin-win-vulkan-x64.zip",
        "cache": "llama-b10686-bin-win-vulkan-x64.zip",
        "sha256": "7cd08366b3a7fbbe787d4e2f27d779c07e486508b2a4c47a5d3d8394fb8c7bd7",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("RUN:", " ".join(args), flush=True)
    return subprocess.run(args, cwd=ROOT, text=True, check=check)


def download(asset: dict[str, object]) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    final = CACHE / str(asset["cache"])
    expected = str(asset["sha256"])
    if final.is_file():
        actual = sha256(final)
        if actual == expected:
            print(f"CACHE OK: {final.name} ({final.stat().st_size:,} bytes)", flush=True)
            return final
        print(f"CACHE SHA mismatch; deleting {final.name}", flush=True)
        final.unlink()
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise SystemExit("curl.exe not found")
    part = final.with_suffix(final.suffix + ".part")
    args = [
        curl,
        "--fail",
        "--location",
        "--retry",
        "6",
        "--retry-delay",
        "5",
        "--continue-at",
        "-",
        "--output",
        str(part),
        str(asset["url"]),
    ]
    print(f"DOWNLOAD: {final.name}", flush=True)
    run(args)
    actual = sha256(part)
    if actual != expected:
        part.unlink(missing_ok=True)
        raise SystemExit(f"SHA256 mismatch for {final.name}: expected={expected} actual={actual}")
    part.replace(final)
    print(f"VERIFIED: {final.name} sha256={actual} size={final.stat().st_size:,}", flush=True)
    return final


def install_model(key: str) -> dict[str, object]:
    asset = ASSETS[key]
    source = download(asset)
    dest = Path(asset["dest"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    expected = str(asset["sha256"])
    if dest.is_file() and sha256(dest) == expected:
        print(f"MODEL OK: {dest.name}", flush=True)
    else:
        shutil.copy2(source, dest)
        actual = sha256(dest)
        if actual != expected:
            dest.unlink(missing_ok=True)
            raise SystemExit(f"model copy verification failed: {dest}")
        print(f"MODEL INSTALLED: {dest.name} ({dest.stat().st_size:,} bytes)", flush=True)
    return {"path": str(dest.relative_to(ROOT)), "sha256": expected, "bytes": dest.stat().st_size, "source": str(asset["url"])}


def install_llama() -> dict[str, object]:
    asset = ASSETS["llama"]
    archive = download(asset)
    extract_root = ROOT / "runtime" / ".llamacpp-b10686"
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(extract_root)
    servers = list(extract_root.rglob("llama-server.exe"))
    if len(servers) != 1:
        raise SystemExit(f"expected exactly one llama-server.exe, found {len(servers)}")
    source_dir = servers[0].parent
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    shutil.copytree(source_dir, RUNTIME)
    shutil.rmtree(extract_root)
    server = RUNTIME / "llama-server.exe"
    vulkan = RUNTIME / "ggml-vulkan.dll"
    if not server.is_file():
        raise SystemExit("llama-server.exe missing after extraction")
    if not vulkan.is_file():
        raise SystemExit("ggml-vulkan.dll missing after extraction")
    version = subprocess.run([str(server), "--version"], cwd=RUNTIME, text=True, capture_output=True, timeout=30)
    version_text = (version.stdout + "\n" + version.stderr).strip()[-2000:]
    print("LLAMA VERSION:\n" + version_text, flush=True)
    return {
        "build": "b10686",
        "archive_sha256": str(asset["sha256"]),
        "source": str(asset["url"]),
        "server": str(server.relative_to(ROOT)),
        "vulkan": str(vulkan.relative_to(ROOT)),
        "version": version_text,
    }


def ensure_build_venv() -> dict[str, str]:
    python = ROOT / ".venv-package" / "Scripts" / "python.exe"
    if not python.is_file():
        base = Path(getattr(sys, "_base_executable", sys.executable))
        run([str(base), "-m", "venv", str(ROOT / ".venv-package")])
    run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements-build.txt"])
    probe = subprocess.run([str(python), "-c", "import PyInstaller,sys; print(sys.version); print(PyInstaller.__version__)"], cwd=ROOT, text=True, capture_output=True, check=True)
    print("BUILD PYTHON:\n" + probe.stdout.strip(), flush=True)
    return {"python": str(python.relative_to(ROOT)), "probe": probe.stdout.strip()}


def ensure_measurement_dependency() -> str:
    test_python = ROOT / ".venv-test" / "Scripts" / "python.exe"
    if not test_python.is_file():
        raise SystemExit(".venv-test Python is missing")
    run([str(test_python), "-m", "pip", "install", "--disable-pip-version-check", "psutil"])
    probe = subprocess.run([str(test_python), "-c", "import psutil; print(psutil.__version__)"], cwd=ROOT, text=True, capture_output=True, check=True)
    return probe.stdout.strip()


def detect_inno() -> str:
    candidates = [
        os.environ.get("ISCC_PATH", ""),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for value in candidates:
        if value and Path(value).is_file():
            print(f"INNO SETUP: {value}", flush=True)
            return value
    print("INNO SETUP: NOT FOUND", flush=True)
    return ""


def env_info() -> dict[str, object]:
    free = shutil.disk_usage(ROOT).free
    gpu = ""
    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        result = subprocess.run(
            [nvidia, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            text=True,
            capture_output=True,
            timeout=30,
        )
        gpu = result.stdout.strip() or result.stderr.strip()
    try:
        import psutil  # type: ignore
        ram = psutil.virtual_memory().total
    except Exception:
        ram = 0
    return {
        "python": sys.version,
        "cpu_count": os.cpu_count(),
        "ram_bytes": ram,
        "disk_free_bytes": free,
        "nvidia": gpu,
        "inno_setup": detect_inno(),
    }


def main() -> int:
    free = shutil.disk_usage(ROOT).free
    print(f"FREE DISK: {free / (1024**3):.1f} GiB", flush=True)
    if free < 20 * 1024**3:
        raise SystemExit("at least 20 GiB free disk is required before downloading release assets")
    MODELS.mkdir(parents=True, exist_ok=True)
    QUALITY.mkdir(parents=True, exist_ok=True)
    e2b = install_model("e2b")
    e4b = install_model("e4b")
    llama = install_llama()
    build_venv = ensure_build_venv()
    psutil_version = ensure_measurement_dependency()
    environment = env_info()
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "e2b": e2b,
        "e4b": e4b,
        "llama_cpp": llama,
        "build_venv": build_venv,
        "psutil": psutil_version,
        "environment": environment,
    }
    (ROOT / "RUNTIME_ASSETS_v1.4.0.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (QUALITY / "runtime_env_v1.4.0.json").write_text(json.dumps(environment, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RELEASE ASSET PREPARATION COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
