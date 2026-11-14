"""Run the labeled SYNTHETIC evaluation set against the current LoopCloser backend.

  cd api && .venv/bin/python ../eval/run_eval.py              # local, in-memory store, full HTTP stack
                                                                # plus the ladder on vs off comparison
  cd api && .venv/bin/python ../eval/run_eval.py --live-latency https://loopcloser-bkdkubo.web.app

Local mode opens fictional cases through the real FastAPI app (TestClient, demo role headers, memory store)
and compares each result with the hand-written label in eval/scenarios.json. Nothing touches Google Cloud.

--live-latency only sends a few READ-ONLY requests (health, today view, one case) to the deployed demo and
reports timings. It never writes, so it does not change what judges see. Gemini is never called.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "api"))
os.environ.setdefault("APP_ENV", "test")
os.environ["DOTENV_DISABLED"] = "1"
os.environ["GEMINI_API_KEY"] = ""  # the eval never calls Gemini

USERS = {
    "worker": "demo-worker-01",
    "coordinator": "demo-coord-01",
    "supervisor": "demo-sup-01",
    "program_manager": "demo-pm-01",
    "patient": "demo-patient-01",
}
ADVANCE = [
    ("reviewed", {}),
    ("patient_notified", {}),
    ("understanding_confirmed", {"source": "staff_confirmed"}),
    ("action_scheduled", {"appointment": {"date": "2026-12-01", "site": "Demo clinic"}}),
    ("visit_completed", {}),
]
TIER_RANK = {"routine": 0, "moderate": 1, "high": 2, "urgent": 3}


def headers(role: str) -> dict[str, str]:
    return {"x-demo-role": role, "x-demo-user": USERS[role]}


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


class Counter:
    """Wraps the memory store and counts what the same calls would cost in Firestore."""

    def __init__(self, repo):
        self.repo, self.writes, self.reads = repo, 0, 0
        orig_append, orig_load, orig_get = repo.append, repo.load_events, repo.get_case

        def append(case_id, events, expected_version, projection):
            self.writes += len(events) + 1  # one create per event + the projection
            self.reads += 1  # transaction read of the case doc
            return orig_append(case_id, events, expected_version, projection)

        def load_events(case_id):
            evs = orig_load(case_id)
            self.reads += max(1, len(evs))
            return evs

        def get_case(case_id):
            self.reads += 1
            return orig_get(case_id)

        repo.append, repo.load_events, repo.get_case = append, load_events, get_case


def run_local(data: dict) -> dict:
    from fastapi.testclient import TestClient

    from loopcloser.config import load_config
    from loopcloser.main import create_app
    from loopcloser.store.memory import MemoryRepository

    os.environ.update(
        {"DEMO_MODE": "true", "RATE_LIMIT_PER_MINUTE": "100000", "RATE_LIMIT_SENSITIVE_PER_MINUTE": "100000"}
    )
    repo = MemoryRepository()
    counter = Counter(repo)
    import logging

    logging.disable(logging.CRITICAL)  # keep the report readable; request logs are not part of the result
    client = TestClient(create_app(load_config(), repo))
    today = date.fromisoformat(client.get("/api/clock", headers=headers("supervisor")).json()["today"])
    defaults = data["defaults"]
    timings: list[float] = []
    per_case_cost: dict[str, tuple[int, int]] = {}

    def call(method: str, url: str, role: str, body: dict | None = None):
        t = time.perf_counter()
        r = client.request(method, url, headers=headers(role), json=body)
        timings.append((time.perf_counter() - t) * 1000)
        return r

    def fill(body):
        s = json.dumps(body).replace("{today+3}", (today + timedelta(days=3)).isoformat())
        return json.loads(s)

    results = []
    for i, sc in enumerate(data["scenarios"]):
        w0, r0 = counter.writes, counter.reads
        o = {**defaults, **sc["open"]}
        days_ago = o.pop("screened_days_ago")
        body = {
            "case_id": f"EVAL-{sc['id']}",
            "participant_id": f"P-9{i:05d}",
            "screening_id": f"S-EVAL-{i}",
            "screened_at": (today - timedelta(days=days_ago)).isoformat(),
            **o,
        }
        res = {"id": sc["id"], "category": sc["category"], "note": sc["note"], "label": sc["label"]}
        r = call("POST", "/api/cases", "coordinator", body)
        label = sc["label"]
        if sc["category"] == "routing":
            if label.get("no_pathway"):
                res["got"] = {"no_pathway": r.status_code == 422}
                res["pass"] = r.status_code == 422
                res["fp"] = res["fn"] = False
                results.append(res)
                continue
            c = r.json()
            due = (date.fromisoformat(c["due_date"]) - date.fromisoformat(body["screened_at"])).days
            got = {
                "pathway_id": c["pathway_id"],
                "clinical_urgency": c["clinical_urgency"],
                "red_flag_open": c["red_flag_open"],
                "due_in_days": due,
            }
            res["got"] = got
            res["pass"] = all(got[k] == v for k, v in label.items())
            # false positive: raised urgency or a red flag the label did not expect; false negative: missed one
            res["fp"] = (got["clinical_urgency"] == "urgent" and label["clinical_urgency"] != "urgent") or (
                got["red_flag_open"] and not label["red_flag_open"]
            )
            res["fn"] = (got["clinical_urgency"] != "urgent" and label["clinical_urgency"] == "urgent") or (
                not got["red_flag_open"] and label["red_flag_open"]
            )
            results.append(res)
            continue
        if r.status_code != 201:
            res.update(pass_=False, error=f"setup: open returned {r.status_code} {r.text[:200]}")
            res["pass"] = False
            results.append(res)
            continue
        case = f"/api/cases/{body['case_id']}"
        setup_ok = True
        if sc.get("advance"):
            for target, extra in ADVANCE:
                rr = call("POST", case + "/transition", "worker", {"target": target, **extra})
                if rr.status_code != 200:
                    setup_ok = False
                    res["error"] = f"setup: advance to {target} returned {rr.status_code} {rr.text[:200]}"
                    break
                if target == sc["advance"]:
                    break
        for st in sc.get("pre", []):
            if not setup_ok:
                break
            rr = call(st.get("method", "POST"), case + st["path"], st["as"], fill(st.get("body")))
            if rr.status_code != 200:
                setup_ok = False
                res["error"] = f"setup: {st['path']} returned {rr.status_code} {rr.text[:200]}"
        if not setup_ok:
            res["pass"] = False
            results.append(res)
            continue
        if "step" in sc:
            st = sc["step"]
            rr = call(st.get("method", "POST"), case + st["path"], st["as"], fill(st.get("body")))
        else:
            rr = call("GET", case, "supervisor")
        out = rr.json() if rr.headers.get("content-type", "").startswith("application/json") else {}
        if sc["category"] == "priority":
            p = out["priority"]
            res["got"] = {"tier": p["tier"], "score": p["score"], "why": [x["rule_id"] for x in p["reasons"]]}
            res["pass"] = p["tier"] == label["tier"] and p["score"] == label["score"]
            res["fp"] = TIER_RANK[p["tier"]] > TIER_RANK[label["tier"]]  # over-prioritized
            res["fn"] = TIER_RANK[p["tier"]] < TIER_RANK[label["tier"]]  # under-prioritized (the risky one)
        elif sc["category"] == "guard":
            allowed = rr.status_code == 200
            got = {"decision": "allow" if allowed else "block", "status": rr.status_code}
            if not allowed and isinstance(out, dict):
                got["rule_id"] = out.get("rule_id")
            ok = got["decision"] == label["decision"]
            if ok and allowed:
                for k in ("state", "automation_paused"):
                    if k in label:
                        got[k] = out.get(k)
                        ok = ok and out.get(k) == label[k]
                if "tier" in label:
                    got["tier"] = out["priority"]["tier"]
                    ok = ok and got["tier"] == label["tier"]
            if ok and not allowed and label.get("rule_id"):
                ok = got.get("rule_id") == label["rule_id"]
            res["got"], res["pass"] = got, ok
            res["fp"] = label["decision"] == "allow" and not allowed  # safe action wrongly blocked
            res["fn"] = label["decision"] == "block" and allowed  # unsafe action wrongly allowed
        elif sc["category"] == "escalation":
            esc = out.get("state") == "escalated"
            res["got"] = {"escalated": esc, "state": out.get("state"), "failed": out.get("failed_contact_attempts")}
            res["pass"] = esc == label["escalated"]
            res["fp"] = esc and not label["escalated"]
            res["fn"] = (not esc) and label["escalated"]
        per_case_cost[sc["id"]] = (counter.writes - w0, counter.reads - r0)
        results.append(res)

    # Full lifecycle cost: open -> 5 human steps -> close with evidence (scenario G02)
    lifecycle = per_case_cost.get("G02")
    return {"today": today.isoformat(), "results": results, "timings_ms": timings, "lifecycle": lifecycle}


LADDER_OFF = '[{"day": 0, "id": "upload", "label": "Result uploaded, case opened"}]'
COMPARE_DAYS = 14


def _arm(ladder_json: str | None, n: int, seed: int) -> dict:
    """Seed the demo cohort into a fresh in-memory store, advance the demo clock one day at a time for
    COMPARE_DAYS days with no staff or patient actions, and measure the open cases on the last day."""
    from fastapi.testclient import TestClient

    from loopcloser.config import load_config
    from loopcloser.domain import indexing as idx
    from loopcloser.domain.events import EventType
    from loopcloser.domain.states import CaseState as S
    from loopcloser.main import create_app
    from loopcloser.store.memory import MemoryRepository

    env = {"DEMO_MODE": "true", "RATE_LIMIT_PER_MINUTE": "100000", "RATE_LIMIT_SENSITIVE_PER_MINUTE": "100000"}
    os.environ.update(env)
    if ladder_json:
        os.environ["LADDER_JSON"] = ladder_json
    else:
        os.environ.pop("LADDER_JSON", None)
    try:
        repo = MemoryRepository()
        client = TestClient(create_app(load_config(), repo))
        seeded = client.post("/api/demo/seed", headers=headers("supervisor"), json={"n": n, "seed": seed}).json()
        for _ in range(COMPARE_DAYS):
            r = client.post("/api/demo/clock", headers=headers("supervisor"), json={"advance_days": 1})
            assert r.status_code == 200, r.text
        today = date.fromisoformat(client.get("/api/clock", headers=headers("supervisor")).json()["today"])
    finally:
        os.environ.pop("LADDER_JSON", None)
    cases = repo.list_cases()
    open_ = [v for v in cases if v.state != S.CLOSED]
    booked = {S.ACTION_SCHEDULED, S.VISIT_COMPLETED}
    overdue = [v for v in open_ if v.state != S.VISIT_COMPLETED and v.due_date and v.due_date < today]
    events = repo.load_events_many([v.id for v in cases])
    red_flag_ids = {v.id for v in cases if v.automation_paused or v.red_flag_open}

    def touched_by_automation_after_flag(cid: str) -> bool:
        flagged = False
        for e in events[cid]:
            if e.type == EventType.RED_FLAG_REPORTED:
                flagged = True
            elif flagged and e.actor.kind == "automation":
                return True
            elif flagged and e.type == EventType.LADDER_STEP:
                return True
        return False

    def contacted(cid: str) -> bool:
        return any(
            e.type == EventType.CONTACT_ATTEMPT
            or (e.type == EventType.NOTIFICATION_STATUS and e.payload.get("status") == "sent")
            for e in events[cid]
        )

    reachable = [v for v in open_ if v.phone_valid and not v.automation_paused]
    return {
        "seeded": seeded.get("opened", 0) + seeded.get("stories", 0),
        "day": COMPARE_DAYS,
        "as_of": today.isoformat(),
        "open": len(open_),
        "unowned": sum(1 for v in open_ if not v.owner),
        "unaccountable": sum(1 for v in open_ if not v.owner and v.state != S.ESCALATED),
        "overdue": len(overdue),
        "silently_overdue": sum(
            1 for v in overdue if v.state not in booked and v.state != S.ESCALATED and not v.automation_paused
        ),
        "reachable_open": len(reachable),
        "reachable_contacted": sum(1 for v in reachable if contacted(v.id)),
        "red_flag_cases": len(red_flag_ids),
        "red_flag_touched_by_automation": sum(1 for c in red_flag_ids if touched_by_automation_after_flag(c)),
        "escalated_queue": sum(1 for v in open_ if v.state == S.ESCALATED),
        "lane_counts": {lane: sum(1 for v in open_ if idx.lane_for(v, today) == lane) for lane in idx.LANES},
    }


def ladder_compare(n: int = 1000, seed: int = 42) -> dict:
    off, on = _arm(LADDER_OFF, n, seed), _arm(None, n, seed)
    pct_on = on["reachable_contacted"] / on["reachable_open"] if on["reachable_open"] else 0.0
    targets = {
        "T1_unaccountable_on_is_0": on["unaccountable"] == 0,
        "T2_silently_overdue_on_is_0": on["silently_overdue"] == 0,
        "T3_unowned_equal": on["unowned"] == off["unowned"],
        "T4_overdue_equal": on["overdue"] == off["overdue"],
        "T5_reachable_contacted_on_at_least_90pct": pct_on >= 0.9,
        "T6_red_flag_untouched_on": on["red_flag_touched_by_automation"] == 0,
    }
    return {
        "cohort": {"n": n, "seed": seed, "data_label": "SIMULATED"},
        "ladder_off": off,
        "ladder_on": on,
        "reachable_contacted_share_on": round(pct_on, 3),
        "targets_met": targets,
        "misses": [k for k, ok in targets.items() if not ok],
    }


def summarize(local: dict) -> dict:
    out = {}
    for cat in ("routing", "priority", "guard", "escalation"):
        rs = [r for r in local["results"] if r["category"] == cat]
        out[cat] = {
            "n": len(rs),
            "pass": sum(1 for r in rs if r["pass"]),
            "false_positives": sum(1 for r in rs if r.get("fp")),
            "false_negatives": sum(1 for r in rs if r.get("fn")),
            "errors": [r["id"] for r in rs if "error" in r],
        }
    t = local["timings_ms"]
    out["latency_ms"] = {
        "requests": len(t),
        "p50": round(statistics.median(t), 2),
        "p95": round(pct(t, 95), 2),
        "max": round(max(t), 2),
    }
    out["failures"] = [
        {k: r.get(k) for k in ("id", "note", "label", "got", "error")} for r in local["results"] if not r["pass"]
    ]
    return out


def live_latency(base: str, n: int) -> dict:
    import urllib.request

    if not base.startswith("https://"):
        raise SystemExit("--live-latency needs an https:// URL")

    def get(path: str, role: str | None = None) -> tuple[int, float, bytes]:
        req = urllib.request.Request(base.rstrip("/") + path, headers=headers(role) if role else {})  # noqa: S310
        t = time.perf_counter()
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - https checked above
            body = r.read()
            code = r.status
        return code, (time.perf_counter() - t) * 1000, body

    res: dict = {}
    code, first, _ = get("/ready")
    res["first_ready_ms"] = round(first, 1)
    for name, path, role in (("health", "/health", None), ("today_supervisor", "/api/today", "supervisor")):
        ts = [get(path, role)[1] for _ in range(n)]
        res[name] = {"n": n, "p50": round(statistics.median(ts), 1), "p95": round(pct(ts, 95), 1)}
    _, _, body = get("/api/today?per_lane=1", "supervisor")
    lanes = json.loads(body)["lanes"]
    cid = next((x["cases"][0]["id"] for x in lanes.values() if x["cases"]), None)
    if cid:
        ts = [get(f"/api/cases/{cid}", "supervisor")[1] for _ in range(n)]
        res["case_detail"] = {"n": n, "p50": round(statistics.median(ts), 1), "p95": round(pct(ts, 95), 1)}
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-latency", metavar="BASE_URL")
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--json", metavar="PATH", help="write full results here")
    ap.add_argument("--no-ladder-compare", action="store_true", help="skip the ladder on vs off comparison")
    a = ap.parse_args()
    data = json.loads((HERE / "scenarios.json").read_text("utf-8"))
    local = run_local(data)
    summary = summarize(local)
    summary["lifecycle_firestore_ops"] = {"writes": local["lifecycle"][0], "reads_approx": local["lifecycle"][1]}
    if not a.no_ladder_compare:
        # Reported, not part of the exit code: misses are listed in EVAL.md.
        summary["ladder_compare"] = ladder_compare()
    if a.live_latency:
        summary["live"] = live_latency(a.live_latency, a.n)
    print(json.dumps(summary, indent=2))
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": summary, "results": local["results"]}, indent=2), "utf-8")
    bad = sum(summary[c]["n"] - summary[c]["pass"] for c in ("routing", "priority", "guard", "escalation"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
