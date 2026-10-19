from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import http.client
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from welfare_search import build_embeddings, build_index

KORDOC_VERSION = "4.0.7"
ORIGINAL_SUFFIXES = {".pdf", ".hwpx", ".hwp", ".docx"}
EMBEDDING_HOST = "127.0.0.1"
EMBEDDING_PORT = 18081
DEFAULT_EMBEDDING_MODEL = "bge-m3-q8_0.gguf"
MATCH_MIN = 0.72
MATCH_MARGIN = 0.08
NAME_NOISE = re.compile(r"\[[^\]]*\]|\([^)]*\)|20\d{2}년?|최종|개정|사업안내|사업|안내|매뉴얼|지침|★|원본")


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Plan:
    original: Path
    target_name: str
    replaces: dict | None
    candidates: tuple[tuple[str, float], ...]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(command: list[str], *, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if check and result.returncode != 0:
        raise UpdateError(f"명령 실패({result.returncode}): {' '.join(command[:3])}\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    return result


def latest_manifest() -> Path:
    manifests = sorted(ROOT.glob("db-update-*.json"))
    if not manifests:
        raise UpdateError("db-update-*.json이 없습니다.")
    return manifests[-1]


def name_key(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"^[0-9a-f]{12}-", "", stem)
    stem = re.sub(r"^\d{2}[._]", "", stem)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", NAME_NOISE.sub("", stem.replace("+", " ").replace("_", " ")))


def target_name(original: Path, category: str) -> str:
    stem = original.stem
    stem = re.sub(r"^\(원본\)\s*", "", stem)
    stem = re.sub(r"^[0-9a-f]{12}-", "", stem)
    stem = re.sub(r"^\d{2}[._]\s*", "", stem)
    stem = re.sub(r"\s+", " ", stem.replace("+", " ").replace("_", " ")).strip()
    if not stem.startswith("[") and category:
        stem = f"[{category}] {stem}"
    return stem + ".md"


def category_of(name: str) -> str:
    match = re.search(r"\[([^\]]+)\]", name)
    return match.group(1) if match else ""


def plan_updates(originals: list[Path], documents: list[dict], mapping: dict[str, dict]) -> tuple[list[Plan], list[dict]]:
    plans: list[Plan] = []
    unresolved: list[dict] = []
    for original in originals:
        scored = sorted(
            ((document["source_name"], difflib.SequenceMatcher(None, name_key(original.name), name_key(document["source_name"])).ratio()) for document in documents),
            key=lambda item: item[1],
            reverse=True,
        )
        candidates = tuple((name, round(score, 3)) for name, score in scored[:3])
        override = mapping.get(original.name)
        if override is not None:
            replaced_name = override.get("replaces")
            replaces = next((document for document in documents if document["source_name"] == replaced_name), None)
            if replaced_name and replaces is None:
                raise UpdateError(f"매핑의 교체 대상이 현재 DB에 없습니다: {replaced_name}")
            category = override.get("category") or (category_of(replaced_name or "") if replaced_name else "")
            if not replaces and not category and not override.get("name"):
                raise UpdateError(f"새 문서는 매핑에 category 또는 name이 필요합니다: {original.name}")
            plans.append(Plan(original, override.get("name") or target_name(original, category), replaces, candidates))
            continue
        best, second = scored[0][1], scored[1][1] if len(scored) > 1 else 0.0
        if best >= MATCH_MIN and best - second >= MATCH_MARGIN:
            replaces = next(document for document in documents if document["source_name"] == scored[0][0])
            plans.append(Plan(original, target_name(original, category_of(replaces["source_name"])), replaces, candidates))
        else:
            unresolved.append({"original": original.name, "candidates": candidates})
    targets = [plan.target_name for plan in plans]
    if len(set(targets)) != len(targets):
        raise UpdateError("새 문서 이름이 겹칩니다: " + ", ".join(targets))
    replaced = [plan.replaces["source_name"] for plan in plans if plan.replaces]
    if len(set(replaced)) != len(replaced):
        raise UpdateError("한 문서를 두 원본이 교체하려고 합니다: " + ", ".join(replaced))
    return plans, unresolved


def kordoc_cli(cache: Path) -> Path:
    cli = cache / "node_modules" / "kordoc" / "dist" / "cli.js"
    package = cache / "node_modules" / "kordoc" / "package.json"
    if cli.exists() and json.loads(package.read_text(encoding="utf-8"))["version"] == KORDOC_VERSION:
        return cli
    cache.mkdir(parents=True, exist_ok=True)
    npm = ["cmd", "/c", "npm"] if os.name == "nt" else ["npm"]
    run([*npm, "install", "--prefix", str(cache), f"kordoc@{KORDOC_VERSION}", "--save-exact", "--no-audit", "--no-fund"], cwd=cache)
    return cli


def convert(cli: Path, original: Path, bundle: Path) -> tuple[dict, Path]:
    original_hash = sha256_bytes(original.read_bytes())
    output = bundle / f"{original_hash[:12]}.json"
    if not output.exists():
        run(["node", str(cli), str(original), "--format", "json", "-o", str(output)])
    payload = json.loads(output.read_text(encoding="utf-8"))
    if not payload.get("success", True) or not payload.get("markdown", "").strip():
        raise UpdateError(f"변환 결과가 비었습니다: {original.name}")
    return payload, output


def low_text_pages(payload: dict) -> list[int]:
    return [int(page["page"]) for page in payload.get("pageQuality", []) if page.get("needsOcr")]


def embedding_model(db: Path) -> str:
    with sqlite3.connect(db) as connection:
        row = connection.execute("SELECT model FROM embeddings GROUP BY model ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    return str(row[0]) if row else DEFAULT_EMBEDDING_MODEL


def embedding_ready() -> bool:
    connection = http.client.HTTPConnection(EMBEDDING_HOST, EMBEDDING_PORT, timeout=2)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        return response.status == 200 and json.loads(response.read().decode("utf-8")).get("status") == "ok"
    except (OSError, ValueError):
        return False
    finally:
        connection.close()


def start_embedding_server() -> subprocess.Popen[bytes] | None:
    if embedding_ready():
        return None
    server = ROOT / "runtime" / "llamacpp" / "llama-server.exe"
    model = ROOT / "models" / DEFAULT_EMBEDDING_MODEL
    if not server.exists() or not model.exists():
        raise UpdateError("임베딩 서버(runtime/llamacpp/llama-server.exe) 또는 bge-m3 모델이 없습니다.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(server), "-m", str(model), "--embedding", "--host", EMBEDDING_HOST, "--port", str(EMBEDDING_PORT), "-c", "2048", "-b", "2048", "-ub", "2048", "-t", "8", "-np", "1", "-ngl", "0", "--no-webui"],
        cwd=server.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
    )
    for _ in range(120):
        if embedding_ready():
            return process
        if process.poll() is not None:
            raise UpdateError("임베딩 서버가 시작 중 종료됐습니다.")
        time.sleep(1)
    process.terminate()
    raise UpdateError("임베딩 서버가 120초 안에 준비되지 않았습니다.")


def database_counts(db: Path) -> dict[str, int]:
    with sqlite3.connect(db) as connection:
        return {
            "documents": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "sections": connection.execute("SELECT COUNT(*) FROM sections").fetchone()[0],
            "embeddings": connection.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0],
            "quality_errors": connection.execute("SELECT COUNT(*) FROM quality_issues WHERE severity='error'").fetchone()[0],
            "references": connection.execute("SELECT COUNT(*) FROM references_map").fetchone()[0],
        }


def section_counts(db: Path, names: list[str]) -> dict[str, int]:
    with sqlite3.connect(db) as connection:
        return {name: connection.execute("SELECT COUNT(*) FROM sections WHERE source_name = ?", (name,)).fetchone()[0] for name in names}


README_RULES = (
    (r"(\| 검색 구간 \| )[\d,]+(개, float16 임베딩 )[\d,]+(개 \|)", lambda c: (f"{c['sections']:,}", f"{c['sections']:,}")),
    (r"(\| 원문 총량 \| )[\d,]+(바이트 \|)", lambda c: (f"{c['source_bytes']:,}",)),
    (r"(- 원문 문서: \*\*)[\d,]+(개\*\*)", lambda c: (f"{c['documents']:,}",)),
    (r"(- 원문 총량: \*\*)[\d,]+(바이트\*\*)", lambda c: (f"{c['source_bytes']:,}",)),
    (r"(- 검색 구간: \*\*)[\d,]+(개\*\*)", lambda c: (f"{c['sections']:,}",)),
    (r"(- 임베딩: \*\*매뉴얼 구간 )[\d,]+(개)", lambda c: (f"{c['sections']:,}",)),
    (r"(- 검색 인덱스 DB: \*\*)[\d,]+(바이트 \(약 )[\d.]+(MiB\)\*\*)", lambda c: (f"{c['db_bytes']:,}", f"{c['db_bytes'] / 1048576:.1f}")),
    (r"(문서별 원본 파일과 해시는 `)db-update-[\d-]+\.json(`)", lambda c: (c["manifest"],)),
)


def update_readme(counts: dict) -> list[str]:
    path = ROOT / "README.md"
    raw = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    missing: list[str] = []
    for pattern, values in README_RULES:
        groups = values(counts)

        def replace(match: re.Match[str], groups: tuple[str, ...] = groups) -> str:
            parts = match.groups()
            return "".join(part + (groups[index] if index < len(groups) else "") for index, part in enumerate(parts))

        text, count = re.subn(pattern, replace, text)
        if count == 0:
            missing.append(pattern)
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return missing


def changed_programs(before: dict, after: dict) -> list[str]:
    def key(program: dict) -> tuple[str, str, str]:
        return (program["name"], program.get("scope", ""), program.get("region_basis", ""))

    old = {key(program): program for program in before["programs"]}
    return sorted(program["name"] for program in after["programs"] if old.get(key(program)) != program)


def write_report(path: Path, context: dict) -> None:
    rows = "\n".join(
        f"| {item['replaces'] or '(새 문서)'} | {item['source_name']} | {item['page_count']} | {item['sections']} | {', '.join(map(str, item['low_text_pages'])) or '-'} |"
        for item in context["documents"]
    )
    programs = ", ".join(context["changed_programs"]) or "없음"
    text = f"""# 복지DB 업데이트 ({context['date']})

`tools/manual_update.py`로 갱신함. 원본 폴더: `{context['originals']}`

## 교체·추가 문서

| 이전 문서 | 새 문서 | 쪽수 | 구간 | 글자 층이 거의 없는 쪽 |
| --- | --- | ---: | ---: | --- |
{rows}

- 변환: kordoc {KORDOC_VERSION} 기본 옵션(JSON 출력의 markdown)
- 글자 층이 거의 없는 쪽은 표지·간지이거나 내용이 그림으로만 들어 있는 쪽임. OCR 보충은 하지 않음.
- 문서별 원본·본문 해시: `{context['manifest']}`

## DB 구성

| 항목 | 이전 | 이번 |
| --- | ---: | ---: |
| 문서 | {context['before']['documents']:,} | {context['after']['documents']:,} |
| 검색 구간 | {context['before']['sections']:,} | {context['after']['sections']:,} |
| 매뉴얼 구간 임베딩 | {context['before']['embeddings']:,} | {context['after']['embeddings']:,} |
| 참조 | {context['before']['references']:,} | {context['after']['references']:,} |
| 품질 오류 | {context['before']['quality_errors']} | {context['after']['quality_errors']} |
| DB SHA-256 | `{context['db_before']}` | `{context['db_after']}` |

새로 계산한 임베딩: {context['embedded']}개

## 사업 사전

다시 만든 결과 출처가 바뀐 사업: {programs}

## 검증

{context['tests']}
"""
    path.write_text(text, encoding="utf-8")


def git_push() -> None:
    for attempt in range(1, 4):
        result = run(["git", "push", "origin", "HEAD"], check=False)
        if result.returncode == 0:
            return
        print(f"GitLab push 실패({attempt}/3), 60초 뒤 다시 시도합니다.", file=sys.stderr)
        time.sleep(60)
    raise UpdateError("GitLab push가 3번 실패했습니다. 나중에 git push origin HEAD를 다시 실행하세요.")


def main() -> int:
    parser = argparse.ArgumentParser(description="매뉴얼 원본 폴더로 복지DB를 갱신한다.")
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--map", type=Path)
    parser.add_argument("--date", default=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat())
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    if run(["git", "status", "--porcelain", "--", "source-md"], check=False).stdout.strip():
        raise UpdateError("source-md에 커밋하지 않은 변경이 있습니다. 먼저 정리하세요.")
    previous_path = latest_manifest()
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    manifest_name = f"db-update-{args.date}.json"
    originals = sorted(path for path in args.originals.rglob("*") if path.suffix.lower() in ORIGINAL_SUFFIXES)
    if not originals:
        raise UpdateError("원본 폴더에 PDF·HWPX·HWP·DOCX가 없습니다.")
    mapping = json.loads(args.map.read_text(encoding="utf-8")) if args.map else {}
    plans, unresolved = plan_updates(originals, previous["documents"], mapping)
    plan_view = [{"original": plan.original.name, "new_name": plan.target_name, "replaces": plan.replaces["source_name"] if plan.replaces else None, "candidates": plan.candidates} for plan in plans]
    if unresolved or args.plan_only:
        print(json.dumps({"plan": plan_view, "unresolved": unresolved}, ensure_ascii=False, indent=1))
        if unresolved:
            print("교체 대상을 정하지 못한 원본이 있습니다. --map 파일로 replaces(또는 새 문서의 category)를 지정하세요.", file=sys.stderr)
            return 3
        return 0
    if (ROOT / manifest_name).exists():
        raise UpdateError(f"{manifest_name}이 이미 있습니다. --date를 바꾸세요.")
    bundle = args.bundle or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "BokjiTalkManualUpdate" / args.date
    bundle.mkdir(parents=True, exist_ok=True)
    cli = kordoc_cli(bundle.parent / f"kordoc-{KORDOC_VERSION}")
    db = ROOT / "wiki" / "kb-v120" / "welfare.db"
    before = database_counts(db)
    db_before = sha256_bytes(db.read_bytes())
    documents = [dict(document) for document in previous["documents"]]
    converted: list[dict] = []
    for plan in plans:
        payload, json_path = convert(cli, plan.original, bundle)
        body = payload["markdown"].encode("utf-8")
        original_bytes = plan.original.read_bytes()
        if plan.replaces:
            run(["git", "rm", "-q", "--", f"source-md/{plan.replaces['source_name']}"])
        (ROOT / "source-md" / plan.target_name).write_bytes(body)
        entry = {
            "source_name": plan.target_name,
            "source_path": f"source-md/{plan.target_name}",
            "original_name": plan.original.name,
            "original_relative_path": f"{args.originals.name}/{plan.original.relative_to(args.originals).as_posix()}",
            "original_sha256": sha256_bytes(original_bytes),
            "format": plan.original.suffix.lower().lstrip("."),
            "page_count": int(payload.get("metadata", {}).get("pageCount") or len(payload.get("pageQuality", [])) or 0) or None,
            "sha256": sha256_bytes(body),
            "bytes": len(body),
            "legacy_serial": plan.replaces.get("legacy_serial") if plan.replaces else None,
            "legacy_source_name": plan.replaces.get("legacy_source_name") if plan.replaces else None,
            "content_source": f"kordoc_{KORDOC_VERSION}_{args.date}",
            "kordoc_json": json_path.name,
            "low_text_pages": low_text_pages(payload),
        }
        if plan.replaces:
            entry["replaces"] = plan.replaces["source_name"]
            entry["replaces_original_sha256"] = plan.replaces.get("original_sha256")
            index = next(i for i, document in enumerate(documents) if document["source_name"] == plan.replaces["source_name"])
            documents[index] = entry
        else:
            documents.append(entry)
        converted.append(entry)
    names = sorted(path.name for path in (ROOT / "source-md").glob("*.md"))
    if names != sorted(document["source_name"] for document in documents):
        raise UpdateError("source-md 파일 목록과 출처 기록이 맞지 않습니다.")
    manifest = {
        "update": args.date,
        "basis": f"{args.originals.name}의 원본 {len(converted)}개 반영(tools/manual_update.py)",
        "parser": previous.get("parser", "") + f" / {args.date} 반영분: kordoc {KORDOC_VERSION} (기본 옵션)",
        "document_count": len(documents),
        "source_bytes": sum(document["bytes"] for document in documents),
        "previous": {"update": previous["update"], "documents": previous["document_count"], "manifest": previous_path.name},
        "replaced": [{"source_name": plan.replaces["source_name"], "sha256": plan.replaces["sha256"], "original_name": plan.replaces.get("original_name")} for plan in plans if plan.replaces],
        "documents": documents,
    }
    (ROOT / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    build_index(ROOT / "source-md", ROOT / "wiki" / "kb-v120")
    server = start_embedding_server()
    try:
        embedding = build_embeddings(db, embedding_model(db))
    finally:
        if server is not None:
            server.terminate()
    after = database_counts(db)
    if after["embeddings"] != after["sections"]:
        raise UpdateError(f"임베딩 {after['embeddings']}개가 구간 {after['sections']}개와 다릅니다.")
    if after["quality_errors"]:
        raise UpdateError(f"품질 오류 {after['quality_errors']}건이 있습니다.")
    sections = section_counts(db, [entry["source_name"] for entry in converted])
    dictionary_path = ROOT / "resources" / "program_dictionary.json"
    dictionary_before = json.loads(dictionary_path.read_text(encoding="utf-8"))
    snapshot = max((ROOT / "quality" / "program_dictionary").glob("source_snapshot_*"))
    audit = ROOT / "quality" / "program_dictionary" / f"build_{args.date.replace('-', '')}"
    run([sys.executable, "-X", "utf8", "tools/build_program_dictionary.py", "--snapshot", str(snapshot.relative_to(ROOT)), "--db", "wiki/kb-v120/welfare.db", "--audit-dir", str(audit.relative_to(ROOT)), "--corpus-manifest", manifest_name])
    dictionary_after = json.loads(dictionary_path.read_text(encoding="utf-8"))
    db_after = sha256_bytes(db.read_bytes())
    readme_missing = update_readme({**after, "source_bytes": manifest["source_bytes"], "db_bytes": db.stat().st_size, "manifest": manifest_name})
    tests = "시험 생략(--skip-tests)"
    if not args.skip_tests:
        result = run([sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-p", "no:cacheprovider"], check=False)
        tail = [line for line in result.stdout.splitlines() if line.strip()][-1:]
        tests = f"pytest: {tail[0] if tail else result.returncode}"
        if result.returncode != 0:
            raise UpdateError("pytest 실패:\n" + result.stdout[-3000:])
    report = ROOT / f"DB_UPDATE_{args.date}.md"
    write_report(report, {
        "date": args.date, "originals": args.originals.name, "manifest": manifest_name, "before": before, "after": after,
        "db_before": db_before, "db_after": db_after, "embedded": embedding.get("embedded", 0), "tests": tests,
        "changed_programs": changed_programs(dictionary_before, dictionary_after),
        "documents": [{**entry, "replaces": entry.get("replaces"), "sections": sections[entry["source_name"]]} for entry in converted],
    })
    summary = {
        "manifest": manifest_name, "report": report.name, "bundle": str(bundle), "documents": len(documents),
        "sections": after["sections"], "embedded": embedding.get("embedded", 0), "db_sha256": db_after,
        "readme_rules_missing": readme_missing, "converted": converted,
    }
    if not args.no_commit:
        run(["git", "add", "--", "source-md", manifest_name, report.name, "README.md", "resources/program_dictionary.json", str(audit.relative_to(ROOT))])
        titles = ", ".join(Path(entry["source_name"]).stem for entry in converted)
        run(["git", "commit", "-q", "-m", f"복지DB 업데이트 {args.date}: {titles}"])
        summary["commit"] = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        if args.push:
            git_push()
            summary["pushed"] = True
    (bundle / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UpdateError as error:
        print(f"오류: {error}", file=sys.stderr)
        raise SystemExit(2)
