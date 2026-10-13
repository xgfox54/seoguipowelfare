from __future__ import annotations

import io
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import yaml

from welfare_agent import build_grounded_prompt, build_system_prompt
from welfare_answer_format import (
    OwnerDocument,
    directory_scope_answer,
    is_numeric_overview_question,
    is_numeric_triplet_question,
    is_single_amount_question,
    normalize_single_amount,
    numeric_triplet_grammar,
    render_table_single_amount,
    render_numeric_triplet,
    single_amount_grammar,
    table_single_amount,
)
from welfare_evidence import parse_evidence, prompt_evidence
from welfare_grounding import grounded_line_checker, sanitize_grounded_answer
from welfare_llm import (
    DEFAULT_MODEL_KEY,
    RUNTIME,
    configured_model_choice,
    configured_model_variant,
    generate,
    resolve_choice,
)
from welfare_models import available_choices
from welfare_program_dictionary import ProgramEntry, evidence_mentions, no_source_answer
from welfare_runtime import app_version
from welfare_search import retrieve_context
from welfare_search.query import QueryPlan, plan_query
from welfare_search.search import YearScope, describe_sources, owner_scope, semantic_search_enabled, year_scope
from welfare_decision import database_version, read_policy, run_gate
from welfare_telemetry import note, timed_call, track_answer

StatusValue = str | int | bool | list[dict[str, str | bool]]
NOT_FOUND_ANSWER = "검색된 복지DB에서 질문에 직접 답할 수 있는 근거를 충분히 찾지 못했습니다."


def _configure_console() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _read_runtime_config(kb_dir: Path) -> dict[str, str]:
    config_path = kb_dir / ".openkb" / "config.yaml"
    if not config_path.exists():
        config_path = kb_dir / "config.yaml.example"
    if not config_path.exists():
        return {"model": resolve_choice(DEFAULT_MODEL_KEY).filename, "language": "ko"}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return {
        "model": str(data.get("model", resolve_choice(DEFAULT_MODEL_KEY).filename)),
        "language": str(data.get("language", "ko")),
    }


def initialize_local_state(kb_dir: Path) -> None:
    state_dir = kb_dir / ".openkb"
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / "config.yaml"
    if not config_path.exists() and (kb_dir / "config.yaml.example").exists():
        config_path.write_bytes((kb_dir / "config.yaml.example").read_bytes())
    registry_path = state_dir / "hashes.json"
    if not registry_path.exists():
        registry_path.write_text("{}\n", encoding="utf-8")


def _index_dir(kb_dir: Path) -> Path:
    preferred = kb_dir / "wiki" / "kb-v120"
    if (preferred / "welfare.db").exists() or (preferred / "manifest.json").exists():
        return preferred
    return kb_dir / "wiki" / "search"


def _runtime_status() -> tuple[str, str, list[dict[str, str | bool]]]:
    return RUNTIME.state, RUNTIME.error, list(available_choices())


def _active_model() -> tuple[str, str]:
    loaded = RUNTIME.model
    if loaded is None:
        configured = configured_model_choice()
        return configured.key, configured.filename
    return loaded.key, loaded.filename


def system_status(kb_dir: Path) -> dict[str, StatusValue]:
    index_dir = _index_dir(kb_dir)
    database = index_dir / "welfare.db"
    manifest_path = index_dir / "manifest.json"
    engine_state, engine_error, models = _runtime_status()
    active_key, active_filename = _active_model()
    configured = configured_model_choice()
    ai_ready = (
        engine_state == "ready"
        and RUNTIME.model is not None
        and RUNTIME.model.key == configured.key
        and any(model["available"] is True for model in models)
    )
    setup_required = engine_state == "error"
    if not database.exists() or not manifest_path.exists():
        return {
            "status": "점검 필요",
            "model": active_filename,
            "app_version": app_version(),
            "source_documents": 0,
            "search_sections": 0,
            "native_openkb_documents": 0,
            "source_bytes": 0,
            "models": models,
            "default_model": active_key,
            "engine_state": engine_state,
            "engine_error": engine_error,
            "ai_ready": ai_ready,
            "setup_required": setup_required,
            "semantic_search": semantic_search_enabled(),
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with sqlite3.connect(database) as connection:
        documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        sections = connection.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        fts_sections = connection.execute("SELECT COUNT(*) FROM sections_fts").fetchone()[0]
    registry_path = kb_dir / ".openkb" / "hashes.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
    healthy = (
        documents == manifest["document_count"]
        and sections == manifest["section_count"]
        and sections == fts_sections
        and documents > 0
    )
    return {
        "status": "정상" if healthy else "점검 필요",
        "model": active_filename,
        "app_version": app_version(),
        "source_documents": documents,
        "search_sections": sections,
        "native_openkb_documents": len(registry),
        "source_bytes": manifest["source_bytes"],
        "models": models,
        "default_model": active_key,
        "engine_state": engine_state,
        "engine_error": engine_error,
        "ai_ready": ai_ready,
        "setup_required": setup_required,
        "semantic_search": semantic_search_enabled(),
    }


def _llm_generate(
    model_tag: str,
    prompt: str,
    timeout: int = 600,
    *,
    system_prompt: str | None = None,
    temperature: float = 0.0,
    grammar: str | None = None,
) -> str:
    configured = configured_model_choice()
    requested_filename = Path(model_tag).name
    if requested_filename != configured.filename:
        raise RuntimeError(
            f"현재 {configured_model_variant()} 배포판에서는 {configured.filename}만 사용할 수 있습니다."
        )
    if RUNTIME.model is not None and RUNTIME.model.filename != configured.filename:
        raise RuntimeError(
            f"실제 로딩 모델({RUNTIME.model.filename})이 빌드 지정 모델({configured.filename})과 다릅니다."
        )
    return generate(
        prompt,
        system_prompt=system_prompt or build_system_prompt(),
        temperature=temperature,
        timeout=timeout,
        grammar=grammar,
    )


def _generate_structured(model_filename: str, prompt: str, grammar: str) -> str:
    """Grammar-constrained generation with one plain fallback on engine rejection."""
    try:
        return _llm_generate(model_filename, prompt, grammar=grammar)
    except RuntimeError as error:
        if "응답 오류" not in str(error):
            raise
        return _llm_generate(model_filename, prompt)


def _directory_owner_answer(database: Path, question: str, context: str) -> str | None:
    """Numeric overview whose owning source is a facility directory.

    Used when the evidence is empty or consists only of that directory: a
    directory lists facilities, it does not define amounts/counts/periods.
    """
    owner = owner_scope(database, question)
    if not owner.directory_sources:
        return None
    blocks = parse_evidence(context) if context.strip() else ()
    if context.strip() and not blocks:
        return None
    if any(block.metadata.get('source_name', '') not in owner.directory_sources for block in blocks):
        return None
    owners = tuple(
        OwnerDocument(
            source_name=str(item["source_name"]), original_name=str(item["original_name"]),
            source_role=str(item["source_role"]), topic=str(item["topic"]),
            start_line=int(item["start_line"]), end_line=int(item["end_line"]),
        )
        for item in describe_sources(database, owner.directory_sources)
    )
    note('numeric_render', {'mode': 'directory_scope', 'owners': len(owners)})
    return sanitize_grounded_answer(directory_scope_answer(owners, question), "", question,
                                    review_complete=True, generation_truncated=False)


def _current_year() -> int:
    return date.today().year


def _plan_diagnostics(plan: QueryPlan) -> dict[str, object]:
    """Decision log of the query plan: fixed-vocabulary labels only, never question text."""
    return {
        "explicit_programs": list(plan.explicit_programs), "tasks": list(plan.tasks),
        "case_conditions": list(plan.case_conditions), "requested_years": sorted(plan.requested_years),
        "excluded_programs": list(plan.excluded_programs), "excluded_years": list(plan.excluded_years),
        "jurisdiction": plan.jurisdiction,
    }


def _evidence_summary(context: str) -> dict[str, object]:
    blocks = parse_evidence(context) if context.strip() else ()
    return {
        "blocks": len(blocks),
        "top1_source": blocks[0].metadata.get("source_name", "") if blocks else "",
        "sources": len({block.metadata.get("source_name", "") for block in blocks}),
        "years": sorted({block.metadata.get("year", "") for block in blocks if block.metadata.get("year", "")}),
    }


def _program_label(plan: QueryPlan, owners: tuple[dict[str, object], ...]) -> str:
    if plan.explicit_programs:
        names = [p for p in plan.explicit_programs if not any(p != o and p in o for o in plan.explicit_programs)]
        return " ".join(names)
    if plan.program_match.status == "matched":
        return "·".join(program.name for program in plan.program_match.programs)
    topics = tuple(dict.fromkeys(str(item["topic"]) for item in owners if item.get("topic")))
    return "·".join(topics) if topics else "해당"


def _year_mismatch_answer(database: Path, plan: QueryPlan, years: YearScope) -> str:
    """Requested year has no edition in the owning documents: say so, answer nothing else."""
    owners = describe_sources(database, years.owner_sources) if years.owner_sources else ()
    requested = "·".join(sorted(years.requested))
    available = "·".join(years.available)
    lines = [
        f"로컬 DB에는 {requested}년 {_program_label(plan, owners)} 자료가 없습니다. 확인되는 자료는 {available}년판입니다.",
        "",
        f"요청한 {requested}년 자료가 없으므로 다른 연도 자료로 대신 답하지 않았습니다. "
        f"{available}년판 내용이 필요하면 연도를 {available}년으로 바꾸거나 연도 없이 다시 질문해 주세요.",
    ]
    if owners:
        lines += ["", "## 📚 확인되는 원문"]
        lines += [f"- {item['original_name'] or item['source_name']}" for item in owners]
    note("notice", {"kind": "year_mismatch", "requested": sorted(years.requested), "available": list(years.available)})
    return "\n".join(lines)


def _programs_without_source(plan: QueryPlan, context: str) -> tuple[ProgramEntry, ...]:
    """Dictionary-matched programmes that the 복지톡 DB has no source for.

    Only when no explicit programme anchor was recognised, every matched
    programme has no source in the whole 복지톡 DB (build-time search), and no
    retrieved evidence names it by what the user typed or by its full name.
    """
    match = plan.program_match
    if plan.explicit_programs or match.status != "matched" or not match.programs:
        return ()
    if any(program.source_status != "none" for program in match.programs):
        return ()
    texts = [f"{block.metadata.get('title', '')} {block.metadata.get('heading_path', '')} {block.body}"
             for block in (parse_evidence(context) if context.strip() else ())]
    if evidence_mentions(match.programs, texts, match.evidence_terms):
        return ()
    return match.programs


def _with_edition_notice(answer: str, plan: QueryPlan, context: str) -> str:
    """No year asked and the newest evidence edition predates this year: say which edition."""
    if plan.requested_years:
        return answer
    years = [int(block.metadata.get("year", "")) for block in parse_evidence(context)
             if str(block.metadata.get("year", "")).isdigit()]
    if not years or max(years) >= _current_year():
        return answer
    note("notice", {"kind": "latest_edition", "year": str(max(years))})
    return f"※ 확인되는 최신 자료는 {max(years)}년판입니다.\n\n{answer}"


@track_answer
def answer_question(kb_dir: Path, question: str, model_key: str = DEFAULT_MODEL_KEY) -> str:
    from welfare_criterion_amount import criterion_amount, criterion_rate
    from welfare_answer_quality import assess_answer, assessment_notice
    from welfare_program_cards import program_card_answer
    from welfare_target_amount import target_amount
    choice = resolve_choice(model_key)
    configured = configured_model_choice()
    if choice.key != configured.key:
        raise RuntimeError(
            f"현재 설치본은 {configured_model_variant()} 전용이며 {configured.label}만 사용할 수 있습니다."
        )

    is_e2b = configured_model_variant() == "E2B"
    note('model_key', configured.key)
    database = _index_dir(kb_dir) / 'welfare.db'
    plan = plan_query(question)
    note('program_match', plan.program_match.diagnostics())
    note('query_plan', _plan_diagnostics(plan))
    years = timed_call('year_scope', year_scope, database, question)
    note('year_scope', years.diagnostics())
    if years.mismatch:
        return _year_mismatch_answer(database, plan, years)
    if not plan.program_terms and re.search(r"(?:신청|지원).*(?:기준|자격|조건)", question):
        directory_answer = _directory_owner_answer(database, question, "")
        if directory_answer is not None:
            return directory_answer
    context = timed_call('retrieval', retrieve_context,
        database,
        question,
        limit=5 if is_e2b else 7,
        char_budget=9_000 if is_e2b else 14_000,
    )
    note('evidence_summary', _evidence_summary(context))
    missing_programs = _programs_without_source(plan, context)
    if missing_programs:
        note('notice', {'kind': 'no_source', 'programs': [program.id for program in missing_programs]})
        return no_source_answer(missing_programs)
    numeric_overview = is_numeric_overview_question(question)
    if numeric_overview:
        directory_answer = _directory_owner_answer(database, question, context)
        if directory_answer is not None:
            return directory_answer
    if not context.strip():
        return NOT_FOUND_ANSWER
    confidence_labels = re.findall(r"\[confidence:\s*(high|medium|low)\]", context)
    if confidence_labels and all(label == "low" for label in confidence_labels):
        return NOT_FOUND_ANSWER

    policy = read_policy(kb_dir)
    db_version = 'OFF' if str(policy['decision_mode']).upper() == 'OFF' else database_version(database)
    context, gate_report = timed_call('decision', run_gate,
        question, context, configured.key, db_version, policy,
        version_reader=lambda: database_version(database))
    note('gate', gate_report)
    # The model sees a trimmed evidence rendering; validators below keep the
    # full EvidenceContext (all provenance metadata) returned by retrieval.
    prompt = build_grounded_prompt(question, prompt_evidence(context))
    prior_removed = 0
    criterion_answer = (criterion_amount(question, parse_evidence(context))
                        or criterion_rate(question, parse_evidence(context))
                        or target_amount(question, parse_evidence(context)))
    if criterion_answer is not None:
        draft_answer = criterion_answer
        note('numeric_render', {'mode': 'criterion_table'})
    elif (card := program_card_answer(question, plan.explicit_programs, plan.requested_years)) is not None:
        note('numeric_render', {'mode': 'program_card', 'card': card.card_id, 'fields': list(card.fields)})
        assessment = assess_answer(card.text, question)
        note('answer_quality', assessment.to_dict())
        notice = assessment_notice(assessment)
        answer = card.text + (f'\n\n{notice}' if notice else '')
        return _with_edition_notice(answer, plan, card.context)
    elif is_numeric_triplet_question(question):
        draft = timed_call('generation', _generate_structured,
            choice.filename, prompt, numeric_triplet_grammar())
        rendered = render_numeric_triplet(
            draft,
            {block.evidence_id for block in parse_evidence(context)},
            grounded_line_checker(context, question),
        )
        note('numeric_render', {'mode': 'triplet', **rendered.diagnostics()})
        draft_answer = rendered.text
        prior_removed = rendered.removed_items
    elif is_single_amount_question(question):
        table_amount = table_single_amount(question, parse_evidence(context),
                                           plan.explicit_programs, plan.requested_years)
        if table_amount is not None:
            draft_answer = render_table_single_amount(table_amount, plan.explicit_programs)
        else:
            draft_answer = normalize_single_amount(timed_call('generation', _generate_structured,
                choice.filename, prompt, single_amount_grammar()))
        note('numeric_render', {'mode': 'single_amount', 'chars': len(draft_answer),
                                'table_fallback': table_amount is not None})
    else:
        draft_answer = timed_call('generation', _llm_generate,
            choice.filename,
            prompt,
        )
    # E2B and E4B builds share one path: a single generation, then validation.
    answer = timed_call('validation', sanitize_grounded_answer,
        draft_answer,
        context,
        question,
        review_complete=True,
        prior_removed=prior_removed,
    )
    return _with_edition_notice(answer, plan, context)


def _usage() -> str:
    return (
        "사용법:\n"
        "  welfare_assistant.py init\n"
        "  welfare_assistant.py status\n"
        "  welfare_assistant.py ask <질문>\n"
        "  welfare_assistant.py <질문>\n"
        f"  현재 배포판: {configured_model_variant()} ({configured_model_choice().filename})"
    )


def main(args: tuple[str, ...]) -> int:
    _configure_console()
    kb_dir = _project_root()
    if not args:
        print(_usage())
        return 2
    if args[0] == "init":
        initialize_local_state(kb_dir)
        print("Local knowledge base initialized.")
        return 0
    if args[0] == "status":
        print(json.dumps(system_status(kb_dir), ensure_ascii=False, indent=2))
        return 0
    model_key = DEFAULT_MODEL_KEY
    remaining = list(args)
    if "--model" in remaining:
        flag_index = remaining.index("--model")
        if flag_index + 1 >= len(remaining):
            print(_usage())
            return 2
        model_key = remaining[flag_index + 1]
        del remaining[flag_index : flag_index + 2]
    try:
        choice = resolve_choice(model_key)
    except KeyError:
        print(_usage())
        return 2
    if choice.key != configured_model_choice().key:
        print(_usage())
        return 2
    question_parts = remaining[1:] if remaining and remaining[0] == "ask" else remaining
    if not question_parts:
        print(_usage())
        return 2
    print(answer_question(kb_dir, " ".join(question_parts), model_key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(tuple(sys.argv[1:])))
