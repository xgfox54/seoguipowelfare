# Beta P0 복구 검증

새 추론이 아닌 저장된 실제 초안 재생 결과입니다.
모델·DB·과거 시험 기록을 변경하지 않았습니다. 전체 정답률·추론 속도 개선은 미측정입니다.

```json
{
  "stage": "completed",
  "kind": "SAVED_DRAFT_REPLAY_NOT_NEW_INFERENCE",
  "model_inference_run": false,
  "original_files": 156,
  "run_dir": "C:\\Users\\xgfox\\Documents\\Codex\\seoguipowelfare-v1.4.0.Beta\\quality\\p0_repair\\20260926T072453313566Z",
  "source_fixture_sha256": "e13f8e956e186f594fe92845934c0fce985018a26639ef0da02759910eb813df",
  "started_utc": "2026-09-26T07:24:53.404251+00:00",
  "decision_mode": "OFF",
  "errors": [],
  "syntax_ok": true,
  "pytest_exit_code": 0,
  "tests": {
    "total": 302,
    "failures": 0,
    "errors": 0,
    "skipped": 0
  },
  "fixture_records": 38,
  "original_unchanged": true,
  "fixture_unchanged": true,
  "numeric_replay": {
    "evaluated": 18,
    "gold_in_draft": 15,
    "gold_in_old_final": 0,
    "gold_in_replayed_final": 15
  },
  "whole_answer_correctness": "UNREVIEWED",
  "new_inference_speedup": "NOT_MEASURED",
  "finished_utc": "2026-09-26T07:30:07.170316+00:00",
  "passed": true
}
```