"""Build the bundled program-name / program-content dictionaries (서귀포시 전용).

Input : a frozen 복지제도100 snapshot (index-lite.json, index-extra.json, items/*.json)
        downloaded once from the integrated-care dashboard, plus the 복지톡 원문 DB.
Output: resources/program_dictionary.json (runtime, offline) and an audit folder.

Scope rules (approved 2026-09-25):
- 중앙부처 사업: all.
- 제주특별자치도 사업: sigungu label '서귀포시' -> seogwipo_confirmed;
  province-wide rows -> seogwipo_confirmed when they appear in the 복지톡
  서귀포 documents (jurisdiction=seogwipo), otherwise jeju_common;
  sigungu label '제주시' -> excluded (제주시 전용).
- Source links are verified against the 복지톡 DB itself; the dashboard's own
  src/talkRefs are hints only.  System manuals and facility lists are never an
  owning source; overview guides are used only when no dedicated manual exists.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from welfare_program_dictionary import SCHEMA, content_tokens, normalize  # noqa: E402
from welfare_search.synonyms import PROGRAM_ANCHORS, PROGRAM_MANUAL_ALIASES  # noqa: E402

PROGRAM_SUFFIX = re.compile(r"(카드|이용권|수당|급여|바우처|서비스|사업|연금|보험|택시|센터|지원금|장려금)$")
LAST_WORD_SUFFIX = re.compile(r"(급여|수당|연금|이용권|바우처|카드|보험|장려금)$")
REGION_PREFIX = re.compile(r"^(제주특별자치도|제주도|제주|서귀포시|서귀포)\s*")
GENERIC_ALIASES = frozenset(normalize(x) for x in (
    "맞춤형 급여", "긴급지원", "생활지원", "주거지원", "의료지원", "돌봄서비스", "복지서비스", "바우처",
    "이용권", "지원사업", "교육지원", "상담지원", "사회서비스", "일자리", "건강관리", "방문서비스",
))
MAX_ALIAS_SHARE = 6
CONTENT_TERMS_PER_ENTRY = 15
GENERIC_WORDS = frozenset(("지원", "사업", "운영", "서비스", "사무", "제공", "및", "등", "지원사업", "관리",
                           "시범사업", "사업운영", "지원금", "등의"))
MIN_KEY_CHARS = 4
MAX_KEY_DOCUMENT_FREQUENCY = 5
# Mention-only linking (programmes with no alias hit): a distinctive partial
# name ('행복택시') found in at most MENTION_MAX_DOCUMENTS manuals/overviews links
# them as "mention_only" sources.  Keys ending in a generic word are never used;
# a short key (4-5 chars) must also be rare in the whole DB (<= 2 sections),
# which rejects common phrases such as '주택마련', '우수학생', '배려대상자'.
MENTION_MIN_KEY_CHARS = 4
MENTION_LONG_KEY_CHARS = 6
MENTION_SHORT_KEY_MAX_SECTIONS = 2
MENTION_MAX_DOCUMENTS = 3
GENERIC_KEY_SUFFIX = re.compile(r"(지원사업|사업|지원|수당|운영|지급|서비스|사용료|요금|지원금|장려금|센터)$")


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_snapshot(snapshot: Path) -> tuple[dict, list[dict], dict[str, dict], dict[str, dict]]:
    lite = json.loads((snapshot / "index-lite.json").read_text(encoding="utf-8"))
    extra = json.loads((snapshot / "index-extra.json").read_text(encoding="utf-8"))
    rows = [dict(zip(lite["fields"], item)) for item in lite["items"]]
    extras = {item[0]: dict(zip(extra["fields"], item)) for item in extra["items"]}
    items = {}
    for path in sorted((snapshot / "items").glob("*.json")):
        items[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return lite, rows, extras, items


def item_view(row: dict, extra: dict, item: dict | None) -> dict:
    """Uniform view of a curated or auto item."""
    view = {"names": [row["n"]], "department": extra.get("d", ""), "content": [row.get("o", "")],
            "hints": set(), "bokjiro_id": ""}
    if not item:
        return view
    if item.get("kind") == "curated":
        record = item.get("record", {})
        extra_block = item.get("extra", {})
        bokjiro = extra_block.get("bokjiro") or {}
        if bokjiro.get("name"):
            view["names"].append(bokjiro["name"])
        view["bokjiro_id"] = bokjiro.get("id", "")
        view["content"] += [record.get("purpose", ""), record.get("target", ""), record.get("benefit", "")]
        view["hints"].update(str(x) for x in record.get("src", []))
        view["hints"].update(str(ref.get("key")) for ref in extra_block.get("talkRefs", []) if isinstance(ref, dict))
    elif item.get("kind") == "auto":
        raw = item.get("raw", {})
        view["bokjiro_id"] = raw.get("id", "")
        view["content"] += [raw.get("summary", ""), raw.get("target", ""), raw.get("benefit", "")]
        view["hints"].update(str(ref.get("key")) for ref in raw.get("talkRefs", []) if isinstance(ref, dict))
    return view


def aliases_for(names: list[str]) -> set[str]:
    aliases: set[str] = set()
    for name in names:
        name = unicodedata.normalize("NFKC", name).strip()
        variants = {name, re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", name).strip()}
        for variant in list(variants):
            stripped = REGION_PREFIX.sub("", variant)
            if stripped != variant and len(normalize(stripped)) >= 4:
                variants.add(stripped)
        for inner in re.findall(r"\(([^)]*)\)", name):
            if len(normalize(inner)) >= 4 and PROGRAM_SUFFIX.search(normalize(inner)):
                variants.add(inner)
        words = name.split()
        if len(words) >= 2 and len(normalize(words[-1])) >= 3 and LAST_WORD_SUFFIX.search(words[-1]):
            variants.add(words[-1])
        aliases.update(normalize(v) for v in variants if len(normalize(v)) >= 3)
    return aliases


def name_fragments(name: str) -> set[str]:
    """Contiguous word groups of a name (without parentheses/region prefix)."""
    core = REGION_PREFIX.sub("", re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", unicodedata.normalize("NFKC", name)))
    words = [w for w in re.split(r"[\s·,/+]+", core) if w]
    fragments: set[str] = set()
    for i in range(len(words)):
        for j in range(i + 1, len(words) + 1):
            group = words[i:j]
            if all(normalize(w) in GENERIC_WORDS for w in group):
                continue
            key = normalize("".join(group))
            if len(key) >= MIN_KEY_CHARS:
                fragments.add(key)
    return fragments


def distinctive_keys(entries: list[dict], document_texts: dict[str, str]) -> None:
    """Partial-name keys that identify exactly one programme ('행복택시', '온정가게').

    A fragment must be unique among programme names and rare in the 복지톡 DB
    (at most MAX_KEY_DOCUMENT_FREQUENCY documents) unless it is an already
    curated programme anchor; common words such as '사회보장' are rejected.
    """
    names = [normalize(e["name"]) for e in entries]
    anchors = {normalize(a) for a in PROGRAM_ANCHORS}
    frequency_cache: dict[str, int] = {}

    def document_frequency(fragment: str) -> int:
        if fragment not in frequency_cache:
            frequency_cache[fragment] = sum(fragment in text for text in document_texts.values())
        return frequency_cache[fragment]

    for entry in entries:
        own = normalize(entry["name"])
        keys = []
        for fragment in sorted(name_fragments(entry["name"])):
            if fragment in entry["aliases"] or fragment in GENERIC_ALIASES:
                continue
            holders = [n for n in names if fragment in n]
            if not holders or set(holders) != {own}:
                continue
            if fragment not in anchors and document_frequency(fragment) > MAX_KEY_DOCUMENT_FREQUENCY:
                continue
            keys.append(fragment)
        # Keep only minimal keys; a key containing a shorter key adds nothing.
        entry["keys"] = sorted(k for k in keys if not any(o != k and o in k for o in keys))


def document_roles(connection: sqlite3.Connection) -> dict[str, dict]:
    roles = {}
    for source_name, topic, authority, jurisdiction, year in connection.execute(
        "SELECT source_name, topic, authority, jurisdiction, year FROM documents"
    ):
        if authority == "index":
            role = "index"
        elif topic == "업무시스템":
            role = "system"
        elif topic == "종합안내":
            role = "overview"
        elif topic == "제도신설":
            # Consultation guideline: cites programmes as examples, never describes them.
            role = "reference"
        else:
            role = "manual"
        roles[source_name] = {"doc": source_name[:2], "role": role, "jurisdiction": jurisdiction, "year": year}
    return roles


def link_sources(aliases: set[str], sections: list[tuple[str, str, str]], roles: dict[str, dict],
                 hints: set[str]) -> tuple[list[dict], str, dict]:
    heading = collections.Counter()
    body = collections.Counter()
    for source_name, head, text in sections:
        for alias in aliases:
            if alias in head:
                heading[source_name] += 1
                break
        else:
            if any(alias in text for alias in aliases):
                body[source_name] += 1
    evidence = {name: {"heading_hits": heading[name], "content_hits": body[name]}
                for name in set(heading) | set(body)}
    manual = [n for n in evidence if roles[n]["role"] == "manual"]
    hinted = {n for n in manual if roles[n]["doc"] in hints}
    owners: list[str] = []
    with_heading = [n for n in manual if heading[n]]
    if with_heading:
        top = max(heading[n] for n in with_heading)
        owners = [n for n in with_heading if heading[n] >= max(1, 0.1 * top) or n in hinted]
        owners.sort(key=lambda n: (heading[n], body[n]), reverse=True)
    else:
        # A single passing mention (e.g. a list line in a common-procedure
        # manual) is not a detailed source; hints only break ties.
        content_docs = [n for n in manual if body[n] >= 2]
        if content_docs:
            top = max(body[n] for n in content_docs)
            owners = [n for n in content_docs if body[n] >= 0.5 * top or n in hinted]
            owners.sort(key=lambda n: (body[n], n in hinted), reverse=True)
    owners = owners[:3]
    status = "manual" if owners else "none"
    if not owners:
        overview = [n for n in evidence if roles[n]["role"] == "overview"]
        overview.sort(key=lambda n: (heading[n], body[n]), reverse=True)
        owners = overview[:2]
        status = "overview_only" if owners else "none"
    linked = [{"source_name": n, "doc": roles[n]["doc"], "role": roles[n]["role"],
               "heading_hits": heading[n], "content_hits": body[n]} for n in owners]
    return linked, status, evidence


def parent_link(name: str, sections: list[tuple[str, str, str]], roles: dict[str, dict]) -> tuple[list[dict], str]:
    """Link a sub-programme to its parent manual, e.g. '긴급복지 교육지원' -> 18번.

    Requires (a) a known parent programme anchor in the name, (b) a manual whose
    filename belongs to that parent, and (c) the remaining words of the name in a
    section heading of that manual.
    """
    compact = normalize(name)
    for anchor in sorted(PROGRAM_ANCHORS, key=len, reverse=True):
        key = normalize(anchor)
        if key not in compact:
            continue
        remainder = compact.replace(key, "")
        remainder = re.sub(r"(사업|운영)$", "", remainder)
        if len(remainder) < 2:
            continue
        manual_keys = [normalize(a) for a in PROGRAM_MANUAL_ALIASES.get(anchor, (anchor,))]
        parents = [n for n, r in roles.items()
                   if r["role"] == "manual" and any(k in normalize(n) for k in manual_keys)]
        hits = collections.Counter(source for source, head, _ in sections
                                   if source in parents and remainder in head)
        if hits:
            owners = [n for n, _ in hits.most_common(2)]
            return ([{"source_name": n, "doc": roles[n]["doc"], "role": "manual", "heading_hits": hits[n],
                      "content_hits": 0, "basis": f"parent:{anchor}"} for n in owners], "manual")
    return [], "none"


def content_terms(entries: list[dict]) -> None:
    frequency = collections.Counter()
    bags = []
    for entry in entries:
        bag = collections.Counter(content_tokens(" ".join([entry["name"], entry["content"]])))
        bags.append(bag)
        frequency.update(bag.keys())
    total = len(entries)
    for entry, bag in zip(entries, bags):
        scored = sorted(bag, key=lambda t: (bag[t] * math.log((total + 1) / (frequency[t] + 0.5)), t), reverse=True)
        entry["content_terms"] = scored[:CONTENT_TERMS_PER_ENTRY]


def link_mentions(entries: list[dict], sections: list[tuple[str, str, str]], roles: dict[str, dict],
                  seogwipo_docs: set[str]) -> int:
    """Second-pass source links for programmes without any alias hit.

    Only distinctive keys (unique among programme names, rare in the DB) that
    are long and not generic are searched; a key must occur in 1..3 manual or
    overview documents.  A 제주 도 단위 programme mentioned in a 서귀포 document
    becomes seogwipo_confirmed (복지톡 DB is the 서귀포 authority).
    """
    linked = 0
    for entry in entries:
        if entry["source_status"] != "none":
            continue
        hits: collections.Counter = collections.Counter()
        used: list[str] = []
        for key in entry["keys"]:
            if len(key) < MENTION_MIN_KEY_CHARS or GENERIC_KEY_SUFFIX.search(key):
                continue
            found = [source for source, head, text in sections if key in head or key in text]
            if len(key) < MENTION_LONG_KEY_CHARS and len(found) > MENTION_SHORT_KEY_MAX_SECTIONS:
                continue
            docs = {source for source in found if roles[source]["role"] in ("manual", "overview")}
            if 0 < len(docs) <= MENTION_MAX_DOCUMENTS:
                hits.update(docs)
                used.append(key)
        if not hits:
            continue
        owners = [name for name, _ in sorted(hits.items(), key=lambda item: (-item[1], item[0]))][:MENTION_MAX_DOCUMENTS]
        entry["sources"] = [{"source_name": name, "doc": roles[name]["doc"], "role": roles[name]["role"],
                             "heading_hits": 0, "content_hits": hits[name], "basis": "mention:" + ",".join(used)}
                            for name in owners]
        entry["source_status"] = "mention_only"
        linked += 1
        in_seogwipo = sorted(roles[name]["doc"] for name in owners if name in seogwipo_docs)
        if entry["region_status"] == "jeju_common" and in_seogwipo:
            entry["region_status"] = "seogwipo_confirmed"
            entry["region_basis"] = f"복지톡 서귀포 문서 언급({','.join(used)}): {','.join(in_seogwipo)}"
    return linked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "resources" / "program_dictionary.json")
    parser.add_argument("--audit-dir", type=Path, required=True)
    args = parser.parse_args()

    lite, rows, extras, items = load_snapshot(args.snapshot)
    connection = sqlite3.connect(args.db)
    roles = document_roles(connection)
    sections = [
        (source, normalize(f"{title} {headings}"), normalize(content))
        for source, title, headings, content in connection.execute(
            "SELECT source_name, title, headings, content FROM sections"
        )
    ]
    seogwipo_docs = {n for n, r in roles.items() if r["jurisdiction"] == "seogwipo"}
    document_texts: dict[str, str] = collections.defaultdict(str)
    for source, head, text in sections:
        document_texts[source] += head + "\n" + text + "\n"

    entries: list[dict] = []
    excluded: list[dict] = []
    for row in rows:
        central = row["g"] == 0
        jeju = "제주" in (row.get("sd") or "")
        if not (central or jeju):
            continue
        sigungu = row.get("sg") or ""
        view = item_view(row, extras.get(row["s"], {}), items.get(row["s"]))
        if jeju and sigungu == "제주시":
            excluded.append({"id": row["s"], "name": row["n"], "reason": "제주시 전용 라벨(sigungu=제주시)"})
            continue
        aliases = aliases_for(view["names"])
        sources, status, evidence = link_sources(aliases, sections, roles, view["hints"])
        if status != "manual":
            parent_sources, parent_status = parent_link(row["n"], sections, roles)
            if parent_sources:
                sources, status = parent_sources, parent_status
        if central:
            region_status, basis = "central", "중앙부처"
        elif sigungu == "서귀포시":
            region_status, basis = "seogwipo_confirmed", "복지제도100 시군구 라벨=서귀포시"
        else:
            in_seogwipo = sorted(n[:2] for n in evidence if n in seogwipo_docs)
            region_status = "seogwipo_confirmed" if in_seogwipo else "jeju_common"
            basis = ("복지톡 서귀포 문서 등장: " + ",".join(in_seogwipo)) if in_seogwipo else "복지톡 서귀포 문서 미등장(도 단위 사업)"
        entries.append({
            "id": row["s"], "name": row["n"], "scope": "central" if central else "jeju",
            "region_status": region_status, "region_basis": basis, "sigungu_label": sigungu,
            "department": view["department"], "category": row.get("c", ""),
            "bokjiro_id": view["bokjiro_id"], "curated": row.get("a") == 1,
            "aliases": sorted(aliases), "content": " ".join(x for x in view["content"] if x)[:600],
            "sources": sources, "source_status": status,
            "_evidence": {n[:2]: v for n, v in sorted(evidence.items())}, "_hints": sorted(view["hints"]),
        })

    # Drop over-shared or generic aliases (never an entry's own canonical name).
    share = collections.Counter(a for e in entries for a in set(e["aliases"]))
    dropped = collections.Counter()
    for entry in entries:
        own = normalize(entry["name"])
        kept = [a for a in entry["aliases"]
                if a == own or (a not in GENERIC_ALIASES and share[a] <= MAX_ALIAS_SHARE)]
        dropped.update(set(entry["aliases"]) - set(kept))
        entry["aliases"] = kept
    content_terms(entries)
    distinctive_keys(entries, document_texts)
    mention_linked = link_mentions(entries, sections, roles, seogwipo_docs)

    built_at = datetime.now(timezone.utc).isoformat()
    runtime = {
        "schema": SCHEMA,
        "built_at": built_at,
        "region_policy": "서귀포시 전용: 중앙부처 + 서귀포시 시행 + 제주 도 단위(서귀포 자료 미확인 표시), 제주시 전용 제외",
        "source": {
            "name": "복지제도100 (전국 통합돌봄 사업 총괄 대시보드)",
            "url": "https://integrated-care-national-dashboard.xgfox54.chatgpt.site/welfare100",
            "as_of": lite.get("asOf"), "origin": lite.get("source"),
            "index_lite_sha256": sha_file(args.snapshot / "index-lite.json"),
            "index_extra_sha256": sha_file(args.snapshot / "index-extra.json"),
            "items": len(items),
        },
        "evidence_db_sha256": sha_file(args.db),
        "usage": "사업 매칭(내비게이션) 전용. 답변 근거·출처로 사용하지 않는다.",
        "counts": {
            "programs": len(entries),
            "central": sum(e["scope"] == "central" for e in entries),
            "seogwipo_confirmed": sum(e["region_status"] == "seogwipo_confirmed" for e in entries),
            "jeju_common": sum(e["region_status"] == "jeju_common" for e in entries),
            "excluded_jeju_city": len(excluded),
            "with_manual_source": sum(e["source_status"] == "manual" for e in entries),
            "overview_only": sum(e["source_status"] == "overview_only" for e in entries),
            "mention_only": sum(e["source_status"] == "mention_only" for e in entries),
            "without_source": sum(e["source_status"] == "none" for e in entries),
            "aliases": sum(len(e["aliases"]) for e in entries),
            "partial_keys": sum(len(e["keys"]) for e in entries),
        },
        "programs": [{k: v for k, v in e.items() if not k.startswith("_")} for e in entries],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(runtime, ensure_ascii=False, indent=1), encoding="utf-8")

    args.audit_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "built_at": built_at, "counts": runtime["counts"], "source": runtime["source"],
        "dropped_aliases": dict(dropped.most_common()),
        "excluded": excluded,
        "programs": [{"id": e["id"], "name": e["name"], "region_status": e["region_status"],
                      "region_basis": e["region_basis"], "source_status": e["source_status"],
                      "sources": [s["doc"] for s in e["sources"]], "evidence": e["_evidence"],
                      "hints": e["_hints"], "aliases": e["aliases"], "keys": e["keys"]} for e in entries],
        "output_sha256": sha_file(args.out),
    }
    (args.audit_dir / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "counts": runtime["counts"], "sha256": audit["output_sha256"]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
