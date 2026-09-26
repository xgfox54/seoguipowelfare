"""Targeted RAG regression and frozen-DB context inspection for A1_FIX."""
from __future__ import annotations
import json, os, re, subprocess, sys, traceback
import defusedxml.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quality" / "rag_focus"
DB = ROOT / "quality" / "real_ab" / "20260920T071621044324Z" / "common_db" / "welfare.db"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
QUESTIONS = {
    "Q063": "기초연금 신청 절차 알려줘",
    "Q088": "노인맞춤돌봄 제외대상이나 예외 조건 알려줘",
    "Q108": "혼자 살고 월소득이 있는 사람이 기초연금을 받을 수 있는지 검토할 때 필요한 조건을 알려줘",
    "Q145": "2026년 생계급여 기준을 알려줘. 2025년 기준과 섞지 말고 2026년 자료만 사용해줘",
    "Q188": "서귀포에서 제주가치돌봄 식사지원 업무를 처리할 때 적용 기준 알려줘",
}

def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def main() -> int:
    run = OUT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run.mkdir(parents=True, exist_ok=False)
    state = {
        "stage":"pytest", "tests":{}, "contexts":{}, "passed":False,
        "started_utc":datetime.now(timezone.utc).isoformat(),
    }
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(ROOT),
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               WELFARE_BETA_DECISION_MODE="OFF")
    xml_path = run / "pytest.xml"
    cmd = [sys.executable,"-X","utf8","-B","-m","pytest","-q","-p","no:cacheprovider",
           "--tb=short","--junitxml="+str(xml_path),"--basetemp="+str(run/"pytest_tmp"),
           "tests/test_context_selection.py","tests/test_retrieval_ranking.py",
           "tests/test_beta_contracts.py","tests/test_beta_p0_repair.py",
           "tests/test_welfare_agent.py"]
    test = subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,
                          encoding="utf-8",errors="replace",timeout=240)
    (run/"pytest.log").write_text(test.stdout+"\n"+test.stderr,encoding="utf-8")
    state["pytest_exit_code"] = test.returncode
    if xml_path.is_file():
        root = ET.parse(xml_path).getroot()
        state["tests"] = {
            "total":len(list(root.iter("testcase"))),
            "failures":len(list(root.iter("failure"))),
            "errors":len(list(root.iter("error"))),
            "skipped":len(list(root.iter("skipped"))),
        }
    if test.returncode:
        state["stage"]="pytest_failed"
        state["finished_utc"]=datetime.now(timezone.utc).isoformat()
        save(run/"summary.json",state); save(OUT/"latest.json",{"run_dir":str(run),**state})
        return 2
    if not DB.is_file():
        state["stage"]="db_missing"; state["finished_utc"]=datetime.now(timezone.utc).isoformat()
        save(run/"summary.json",state); save(OUT/"latest.json",{"run_dir":str(run),**state})
        return 3

    try:
        from welfare_search.context import retrieve_context
        from welfare_evidence import parse_evidence

        state["stage"]="context_replay"
        for qid, question in QUESTIONS.items():
            state["current_question"] = qid
            save(run/"summary.json",state)
            context = retrieve_context(DB, question, limit=6)
            blocks = parse_evidence(context)
            body_text = "\n".join(block.body for block in blocks)
            first_scope = ""
            first_body = ""
            if blocks:
                first_scope = " ".join((
                    blocks[0].metadata.get("title", ""),
                    blocks[0].metadata.get("heading_path", ""),
                ))
                first_body = blocks[0].body
            record = {
            "question": question,
            "evidence_count": len(blocks),
            "context_chars": len(context),
            "blocks": [
                {
                    "id": b.evidence_id,
                    "source": b.metadata.get("source_name",""),
                    "title": b.metadata.get("title",""),
                    "heading_path": b.metadata.get("heading_path",""),
                    "service_names": b.metadata.get("service_names",""),
                    "body_preview": b.body[:500],
                } for b in blocks
            ],
            "contains_income_recognition": ("소득인정액" in body_text or "선정기준액" in body_text),
            "contains_basic_pension_review": (
                "소득인정액" in body_text
                and "선정기준액" in body_text
                and "2,470,000원" in body_text
                and "3,952,000원" in body_text
                and ("단독가구" in body_text and "부부가구" in body_text)
                and "만 65세 이상" in body_text
                and "재산의 소득환산액" in body_text
            ),
            "first_block_is_basic_pension_review": bool(
                blocks
                and "수급권자의 범위" in first_body
                and "소득인정액" in first_body
                and "선정기준액" in first_body
                and "2,470,000원" in first_body
                and "만 65세 이상" in first_body
                and "재산의 소득환산액" in first_body
            ),
            "contains_livelihood_criterion": (
                bool(re.search(r"2026년(?:도)?", body_text))
                and "생계급여 선정기준" in body_text
                and bool(re.search(r"기준\s*중위소득\s*32%|기준중위소득\s*32%", body_text))
                and all(value in body_text for value in ("820,556", "2,078,316", "3,044,848"))
            ),
            "contains_meal_support": "식사지원" in body_text,
            "contains_compact_meal": "간편식" in body_text,
            "contains_donghaeng_service": "동행지원서비스" in body_text,
            "contains_application_flow": (
                "신청" in body_text and "접수" in body_text and
                ("조사" in body_text or "결정" in body_text)
            ),
            "contains_senior_care_exclusion": (
                "제외기준" in body_text
                and "노인장기요양보험 등급자" in body_text
                and bool(re.search(r"가사[･·\-]?간병\s*방문지원사업\s*이용자", body_text))
            ),
            "contains_senior_care_exception": (
                "65세 미만" in body_text
                and "예외승인 불가" in body_text
                and "시장･군수･구청장이 서비스가 필요하다고 인정하는 경우 예외적으로 제공 가능" in body_text
            ),
            "first_block_owned_by_senior_care": "노인맞춤돌봄" in first_scope,
            "first_block_owned_by_home_care": bool(re.search(r"가사[･·\-]?간병", first_scope)),
            "first_block_is_senior_selection": bool(re.search(r"서비스\s*대상자\s*선정|대상자\s*선정", first_scope)),
            "first_block_has_senior_exclusion": bool(
                blocks and "제외기준" in blocks[0].body and "예외" in blocks[0].body
            ),
            "first_block_is_meal_contract": bool(
                blocks
                and "식사지원" in first_scope
                and (
                    "계약서" in first_scope
                    or ("서비스 제공 의뢰서" in first_body and "서비스 결과 보고서" in first_body)
                )
            ),
            "livelihood_context_compact": not (
                qid == "Q145" and len(blocks) > 2
            ),
            }
            state["contexts"][qid] = record
            (run/f"{qid}_context.txt").write_text(context,encoding="utf-8")
            save(run/"summary.json",state)
    except Exception as exc:
        trace = traceback.format_exc()
        (run/"crash.log").write_text(trace, encoding="utf-8")
        state["stage"] = "context_replay_exception"
        state["error_type"] = type(exc).__name__
        state["error"] = str(exc)
        state["traceback"] = trace
        state["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save(run/"summary.json",state)
        save(OUT/"latest.json",{"run_dir":str(run),**state})
        print("RAG_FOCUS_EXCEPTION=" + json.dumps({
            "question": state.get("current_question"),
            "error_type": state["error_type"],
            "error": state["error"],
            "run_dir": str(run),
        }, ensure_ascii=False), flush=True)
        return 5

    structural = (
        state["contexts"]["Q063"]["contains_application_flow"]
        and state["contexts"]["Q088"]["contains_senior_care_exclusion"]
        and state["contexts"]["Q088"]["contains_senior_care_exception"]
        and state["contexts"]["Q088"]["first_block_owned_by_senior_care"]
        and not state["contexts"]["Q088"]["first_block_owned_by_home_care"]
        and state["contexts"]["Q088"]["first_block_is_senior_selection"]
        and state["contexts"]["Q088"]["first_block_has_senior_exclusion"]
        and state["contexts"]["Q108"]["contains_income_recognition"]
        and state["contexts"]["Q108"]["contains_basic_pension_review"]
        and state["contexts"]["Q108"]["first_block_is_basic_pension_review"]
        and state["contexts"]["Q145"]["contains_livelihood_criterion"]
        and state["contexts"]["Q145"]["livelihood_context_compact"]
        and state["contexts"]["Q188"]["contains_meal_support"]
        and state["contexts"]["Q188"]["contains_compact_meal"]
        and not state["contexts"]["Q188"]["contains_donghaeng_service"]
        and state["contexts"]["Q188"]["first_block_is_meal_contract"]
    )
    state["structural_rag_gate_passed"] = structural
    state["passed"] = test.returncode == 0 and structural
    state["stage"] = "completed" if state["passed"] else "rag_gate_failed"
    state["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save(run/"summary.json",state)
    save(OUT/"latest.json",{"run_dir":str(run),**state})
    print("RAG_FOCUS="+json.dumps({
        "stage":state["stage"],"tests":state["tests"],
        "structural_rag_gate_passed":state["structural_rag_gate_passed"],
        "signals":{qid:{
            "count":row["evidence_count"],
            "income":row["contains_income_recognition"],
            "livelihood":row["contains_livelihood_criterion"],
            "meal":row["contains_meal_support"],
            "compact_meal":row["contains_compact_meal"],
            "donghaeng":row["contains_donghaeng_service"],
            "application":row["contains_application_flow"],
            "senior_exclusion":row["contains_senior_care_exclusion"],
            "senior_exception":row["contains_senior_care_exception"],
            "senior_owned":row["first_block_owned_by_senior_care"],
            "home_care_owned":row["first_block_owned_by_home_care"],
            "senior_selection_first":row["first_block_is_senior_selection"],
            "senior_exclusion_first":row["first_block_has_senior_exclusion"],
            "meal_contract_first":row["first_block_is_meal_contract"],
        } for qid,row in state["contexts"].items()},
        "run_dir":str(run)
    },ensure_ascii=False),flush=True)
    return 0 if state["passed"] else 4

if __name__=="__main__":
    raise SystemExit(main())
