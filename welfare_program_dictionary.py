"""Program-name / program-content dictionaries for the local 복지톡 (서귀포시 전용).

The dictionaries answer one question only: *which programme is the user asking
about?*  They are navigation data built from the 복지제도100 snapshot of the
integrated-care dashboard.  Answer text and citations always come from the
복지톡 원문 DB; dictionary content is never used as evidence.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from welfare_runtime import resource_path

DICTIONARY_RELATIVE_PATH = ("resources", "program_dictionary.json")
SCHEMA = "bokjitalk-program-dictionary-v1"
MIN_ALIAS_CHARS = 3
CONTENT_MIN_TERMS = 2
CONTENT_MIN_SCORE = 6.0
CONTENT_MIN_MARGIN = 1.35
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
KOREAN_SUFFIXES = (
    "으로부터", "에게서", "에서는", "으로는", "까지는", "부터는", "에서", "에게", "께서", "으로",
    "처럼", "보다", "까지", "부터", "하며", "하고", "이며", "이고", "과", "와", "을", "를", "은",
    "는", "이", "가", "의", "에", "도", "만", "로",
)
CONTENT_STOPWORDS = frozenset((
    "지원", "대상", "사업", "제공", "위해", "통해", "경우", "관련", "기타", "등의", "위한", "및", "등",
    "서비스", "알려줘", "알려", "기준", "어떻게", "무엇", "있나", "있는지", "해줘", "주세요", "필요",
    "대한", "대해", "사람", "가구", "해당", "신청", "방법", "내용", "경우에", "정도", "얼마",
    # Question-type words say *what* is asked, not *which* programme.
    "금액", "횟수", "기간", "현황", "조건", "자격", "절차", "원문", "수치", "정리", "검토", "판단",
    "예외", "제외", "특례", "중복", "업무", "처리", "적용", "주요", "지원내용", "기준을", "확인",
))


def normalize(text: str) -> str:
    """NFKC, lower-case, whitespace removed: '제주 가치 돌봄' == '제주가치돌봄'."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "")).lower()


def strip_suffix(token: str) -> str:
    for suffix in KOREAN_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            return token[: -len(suffix)]
    return token


def content_tokens(text: str) -> list[str]:
    tokens = (strip_suffix(t) for t in TOKEN_RE.findall(unicodedata.normalize("NFKC", text or "")))
    return [t for t in tokens if len(t) >= 2 and t not in CONTENT_STOPWORDS and not t.isdigit()]


@dataclass(frozen=True)
class ProgramEntry:
    id: str
    name: str
    scope: str                  # central | jeju
    region_status: str          # central | seogwipo_confirmed | jeju_common
    department: str
    aliases: tuple[str, ...]    # normalized
    content_terms: tuple[str, ...]
    source_names: tuple[str, ...]
    source_status: str          # manual | overview_only | mention_only | none
    keys: tuple[str, ...] = ()  # normalized distinctive partial names

    @property
    def has_source(self) -> bool:
        return bool(self.source_names)

    @property
    def identity_terms(self) -> tuple[str, ...]:
        """Normalized strings that identify this programme in evidence text."""
        return tuple(dict.fromkeys((*self.aliases, *self.keys)))


@dataclass(frozen=True)
class ProgramMatch:
    status: str                         # matched | ambiguous | none
    method: str = ""                    # name | partial | content | ""
    programs: tuple[ProgramEntry, ...] = ()
    matched_aliases: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()
    score: float = 0.0

    @property
    def owner_sources(self) -> frozenset[str]:
        if self.status != "matched":
            return frozenset()
        return frozenset(name for program in self.programs for name in program.source_names)

    @property
    def without_source(self) -> tuple[ProgramEntry, ...]:
        return tuple(program for program in self.programs if not program.has_source)

    @property
    def match_terms(self) -> tuple[str, ...]:
        """Normalized names/keys of the matched programmes (for local evidence checks)."""
        if self.status != "matched":
            return ()
        return tuple(dict.fromkeys(term for program in self.programs for term in program.identity_terms))

    @property
    def evidence_terms(self) -> tuple[str, ...]:
        """Terms that show evidence is *about* the matched programme: what the
        user typed (matched name/partial key) plus the programmes' full names.
        Other partial keys are left out; they may be common phrases."""
        if self.status != "matched":
            return ()
        if self.method == "content":
            return self.match_terms
        return tuple(dict.fromkeys((*self.matched_aliases, *(a for p in self.programs for a in p.aliases))))

    def diagnostics(self) -> dict:
        return {
            "status": self.status,
            "method": self.method,
            "programs": [
                {"id": p.id, "name": p.name, "scope": p.scope, "region_status": p.region_status,
                 "source_status": p.source_status, "sources": len(p.source_names)}
                for p in self.programs
            ],
            "candidates": list(self.candidates[:5]),
            "score": round(self.score, 2),
        }


NO_MATCH = ProgramMatch("none")


@dataclass
class ProgramDictionary:
    entries: tuple[ProgramEntry, ...]
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._by_alias: dict[str, list[ProgramEntry]] = {}
        self._by_key: dict[str, list[ProgramEntry]] = {}
        for entry in self.entries:
            for alias in entry.aliases:
                if len(alias) >= MIN_ALIAS_CHARS:
                    self._by_alias.setdefault(alias, []).append(entry)
            for key in entry.keys:
                self._by_key.setdefault(key, []).append(entry)
        # Longest aliases first so that '재가의료급여' wins over '의료급여'.
        self._aliases = sorted(self._by_alias, key=len, reverse=True)
        self._keys = sorted(self._by_key, key=len, reverse=True)
        documents = [set(entry.content_terms) for entry in self.entries]
        frequency: dict[str, int] = {}
        for terms in documents:
            for term in terms:
                frequency[term] = frequency.get(term, 0) + 1
        total = max(1, len(documents))
        self._idf = {term: math.log((total + 1) / (count + 0.5)) for term, count in frequency.items()}

    @classmethod
    def load(cls, path: Path | None = None) -> "ProgramDictionary":
        path = path or resource_path(*DICTIONARY_RELATIVE_PATH)
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema") != SCHEMA:
            raise ValueError("PROGRAM_DICTIONARY_SCHEMA_MISMATCH")
        entries = tuple(
            ProgramEntry(
                id=str(item["id"]), name=str(item["name"]), scope=str(item["scope"]),
                region_status=str(item["region_status"]), department=str(item.get("department", "")),
                aliases=tuple(item["aliases"]), content_terms=tuple(item.get("content_terms", ())),
                source_names=tuple(source["source_name"] for source in item.get("sources", ())),
                source_status=str(item.get("source_status", "none")),
                keys=tuple(item.get("keys", ())),
            )
            for item in payload["programs"]
        )
        return cls(entries, {k: v for k, v in payload.items() if k != "programs"})

    # ------------------------------------------------------------------ matching
    def match(self, query: str, *, excluded: Iterable[str] = ()) -> ProgramMatch:
        """Deterministic programme match: name dictionary first, content second."""
        text = normalize(query)
        for phrase in excluded:
            text = text.replace(normalize(phrase), " ")
        spans = _find_spans(text, self._aliases)
        if spans:
            return self._resolve_names([alias for _, _, alias in sorted(spans)], self._by_alias, "name")
        key_spans = _find_spans(text, self._keys)
        if key_spans:
            matched = self._resolve_names([key for _, _, key in sorted(key_spans)], self._by_key, "partial")
            if matched.status == "matched" and len(matched.programs) > 2:
                return ProgramMatch("ambiguous", "partial", (), matched.matched_aliases, matched.candidates)
            return matched
        return self._match_content(query, excluded)

    def _resolve_names(self, aliases: list[str], index: dict[str, list[ProgramEntry]], method: str) -> ProgramMatch:
        groups: list[tuple[str, tuple[ProgramEntry, ...]]] = []
        for alias in dict.fromkeys(aliases):
            entries = tuple(index[alias])
            groups.append((alias, entries))
        chosen: list[ProgramEntry] = []
        ambiguous: list[str] = []
        for alias, entries in groups:
            owner_sets = {entry.source_names for entry in entries}
            if len(entries) == 1 or len(owner_sets) == 1:
                chosen.append(_preferred(entries))
                continue
            # Same alias, different evidence documents: prefer the entry whose
            # canonical name *is* this alias; otherwise do not guess.
            exact = [entry for entry in entries if normalize(entry.name) == alias]
            if len(exact) == 1:
                chosen.append(exact[0])
            else:
                ambiguous.append(alias)
        unique = tuple(dict.fromkeys(chosen))
        if ambiguous and not unique:
            names = tuple(dict.fromkeys(e.name for a in ambiguous for e in index[a]))
            return ProgramMatch("ambiguous", method, (), tuple(ambiguous), names)
        return ProgramMatch("matched", method, unique, tuple(dict.fromkeys(aliases)),
                            tuple(e.name for e in unique))

    def _match_content(self, query: str, excluded: Iterable[str]) -> ProgramMatch:
        excluded_norm = {normalize(x) for x in excluded}
        terms = {t for t in content_tokens(query) if normalize(t) not in excluded_norm}
        if not terms:
            return NO_MATCH
        scored: list[tuple[float, int, ProgramEntry]] = []
        for entry in self.entries:
            overlap = terms.intersection(entry.content_terms)
            if len(overlap) < CONTENT_MIN_TERMS:
                continue
            score = sum(self._idf.get(term, 0.0) for term in overlap)
            scored.append((score, len(overlap), entry))
        if not scored:
            return NO_MATCH
        scored.sort(key=lambda row: (row[0], row[1], row[2].has_source), reverse=True)
        best, count, entry = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        candidates = tuple(row[2].name for row in scored[:5])
        if best < CONTENT_MIN_SCORE or (second and best / second < CONTENT_MIN_MARGIN):
            return ProgramMatch("ambiguous", "content", (), (), candidates, best)
        # Content matches only steer retrieval; a programme without any 복지톡
        # source is never selected from content alone.
        if not entry.has_source:
            return ProgramMatch("ambiguous", "content", (), (), candidates, best)
        return ProgramMatch("matched", "content", (entry,), (), candidates, best)


def _preferred(entries: tuple[ProgramEntry, ...]) -> ProgramEntry:
    order = {"seogwipo_confirmed": 0, "central": 1, "jeju_common": 2}
    return sorted(entries, key=lambda e: (not e.has_source, order.get(e.region_status, 3), e.id))[0]


def _find_spans(text: str, terms: list[str]) -> list[tuple[int, int, str]]:
    """Non-overlapping occurrences, longest terms first."""
    spans: list[tuple[int, int, str]] = []
    for term in terms:
        start = text.find(term)
        while start >= 0:
            end = start + len(term)
            if not any(s < end and start < e for s, e, _ in spans):
                spans.append((start, end, term))
            start = text.find(term, start + 1)
    return spans


def evidence_mentions(programs: tuple[ProgramEntry, ...], texts: Iterable[str],
                      terms: Iterable[str] | None = None) -> bool:
    """True when any retrieved evidence text names one of the programmes."""
    terms = set(terms) if terms is not None else {term for program in programs for term in program.identity_terms}
    return any(term in normalize(text) for text in texts for term in terms)


@lru_cache(maxsize=4)
def _cached(path_text: str) -> ProgramDictionary | None:
    path = Path(path_text)
    if not path.is_file():
        return None
    return ProgramDictionary.load(path)


def default_dictionary() -> ProgramDictionary | None:
    """Bundled dictionary, or None when the resource is absent (search still works)."""
    return _cached(str(resource_path(*DICTIONARY_RELATIVE_PATH)))


def match_program(query: str, *, excluded: Iterable[str] = ()) -> ProgramMatch:
    dictionary = default_dictionary()
    if dictionary is None:
        return NO_MATCH
    return dictionary.match(query, excluded=tuple(excluded))


REGION_LABEL = {
    "central": "중앙부처 사업",
    "seogwipo_confirmed": "서귀포시 시행 사업",
    "jeju_common": "제주특별자치도 사업(서귀포시 자료 미확인)",
}


def no_source_answer(programs: tuple[ProgramEntry, ...]) -> str:
    """Deterministic notice for a matched programme without any 복지톡 원문."""
    lines = []
    for program in programs:
        label = REGION_LABEL.get(program.region_status, "사업")
        lines.append(
            f"'{program.name}'은(는) 사업명 사전에서 확인되는 {label}이지만, "
            "로컬 복지톡 DB에는 이 사업의 원문 자료가 없습니다."
        )
    lines.append("")
    lines.append("원문 근거가 없어 지원대상·금액·절차를 안내하지 않습니다. "
                 "해당 사업은 소관 부서의 최신 공식자료나 복지로에서 확인해 주세요.")
    return "\n".join(lines)
