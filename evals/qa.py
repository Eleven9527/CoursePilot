"""Run the course QA fixture against a running CoursePilot API."""

import argparse
import json
import re
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

from evals.retrieval import normalize


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/api/v1/qa")
    parser.add_argument("--top-k", type=int, choices=range(1, 11), default=5)
    parser.add_argument("--output", type=Path, default=Path("data/qa-eval.json"))
    args = parser.parse_args()

    fixture = json.loads(Path(__file__).with_name("units_1_2.json").read_text(encoding="utf-8"))
    scope = {"grade": "高一", "unit_start": 1, "unit_end": 2, "top_k": args.top_k}
    cookies = CookieJar()
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
    service = urlsplit(args.api_url)
    login_url = urlunsplit((service.scheme, service.netloc, "/login", "", ""))
    try:
        with opener.open(login_url, data=urlencode({"account": "student", "password": "123"}).encode(),
                         timeout=10):
            pass
    except OSError as exc:
        parser.exit(2, f"Demo login failed: {exc}\n")
    if not any(cookie.name == "session" for cookie in cookies):
        parser.exit(2, "Demo login did not return a session cookie.\n")
    results = []
    for case in fixture["cases"]:
        row = {"id": case["id"], "question": case["question"], "expected_answer": case["answer"]}
        results.append(row)
        body = json.dumps({**scope, "question": case["question"]}).encode()
        for endpoint in (("search", "ask") if case["evidence"] else ("ask",)):
            request = Request(f"{args.api_url.rstrip('/')}/{endpoint}", data=body,
                              headers={"Content-Type": "application/json"})
            try:
                with opener.open(request, timeout=100) as response:
                    row[endpoint] = json.load(response)
            except (URLError, OSError, ValueError) as exc:
                row.setdefault("errors", {})[endpoint] = str(exc)
        expected_intent = case.get("intent")
        if expected_intent:
            row["expected_intent"] = expected_intent
            row["intent_matches"] = {
                endpoint: row.get(endpoint, {}).get("intent") == expected_intent
                for endpoint in ("search", "ask")
            }
        for endpoint in ("search", "ask"):
            if endpoint == "ask" and "forbidden" in case:
                continue
            if endpoint in row and case["evidence"]:
                texts = [normalize(source["text"]) for source in row[endpoint]["sources"]
                         if source["filename"] == fixture["source_filename"]]
                row[f"{endpoint}_evidence"] = [
                    any(all(normalize(part) in text for part in group) for text in texts)
                    for group in case["evidence"]
                ]
        if not case["evidence"] and "ask" in row:
            row["empty_citations"] = not row["ask"]["sources"]
        if "forbidden" in case and "ask" in row:
            row["empty_citations"] = not row["ask"]["sources"]
            answer = normalize(row["ask"]["answer"])
            row["hint_has_no_answer"] = bool(answer) and not any(
                re.search(pattern, answer, re.IGNORECASE) for pattern in case["forbidden"]
            )
        checks = [*row.get("intent_matches", {}).values(), row.get("hint_has_no_answer", True),
                  *row.get("search_evidence", []), *row.get("ask_evidence", []),
                  row.get("empty_citations", True)]
        row["automatic_pass"] = not row.get("errors") and all(checks)
        print(f"{case['id']}: {'PASS' if row['automatic_pass'] else 'FAIL'}", flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"scope": scope, "results": results}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    passed = sum(row["automatic_pass"] for row in results)
    print(f"Automatic checks: {passed}/{len(results)}. Review answers in {args.output}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
