"""Evaluate the handout reviewer with labeled, synthetic exercises."""
import json
from pathlib import Path

from app.api.v1.endpoints.prep import Handout, review_content

QUESTION = "The bridge ___ built last year. A. was B. were C. is"
EVIDENCE = QUESTION + " 正确答案 A，last year 表示过去，bridge 是单数。"
CASES = [
    ("clean", QUESTION, "A. was", "过去时，主语为单数。", EVIDENCE, False),
    ("answer_conflict", QUESTION, "B. were", "主语为单数，应选 A. was。", EVIDENCE, True),
    ("wrong_citation", QUESTION, "A. was", "过去时，主语为单数。", "水的化学式是 H2O。", True),
    ("answer_leak", QUESTION.replace("___", "was（正确答案：A）"), "A. was",
     "过去时，主语为单数。", EVIDENCE, True),
]


def main() -> int:
    results = []
    for name, question, answer, explanation, evidence, expected_issue in CASES:
        draft = Handout(title="被动语态", focus="时态", difficulty="主谓一致", exercises=[
            dict(question=question, answer=answer, explanation=explanation, source=1),
        ])
        row = {"case": name, "expected_issue": expected_issue, "draft": draft.model_dump(),
               "evidence": evidence}
        try:
            issues = review_content(draft, [{"text": evidence}])
            row.update(issues=issues, passed=bool(issues) == expected_issue)
        except (RuntimeError, ValueError) as exc:
            row.update(error=str(exc), passed=False)
        results.append(row)
        print(f"{name}: {'PASS' if row['passed'] else 'FAIL'}", flush=True)
    report = Path("data/prep-review-eval.json")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {report}")
    return int(not all(row["passed"] for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
