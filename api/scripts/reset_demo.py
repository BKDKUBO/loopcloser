"""Operator tool: wipe the SIMULATED demo cases and reset the demo clock, so the judged demo starts clean.

Only cases marked synthetic are deleted (with their event logs). Real cases are never touched. This is a
deliberate exception to "events are append-only", allowed only for fictional demo data, and it is not
exposed through the API. Run from a machine with gcloud application default credentials:

    GOOGLE_CLOUD_QUOTA_PROJECT=loopcloser-bkdkubo \\
      api/.venv/bin/python api/scripts/reset_demo.py --project loopcloser-bkdkubo --yes

The API picks up the reset clock within 30 seconds. Then reseed with the supervisor demo button
or POST /api/demo/seed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ENV = Path(__file__).resolve().parents[2] / "deploy" / "project.env"


def _allowed_project() -> str:
    """Only the LoopCloser project named in deploy/project.env may be reset."""
    m = re.search(r'^PROJECT_ID="?([a-z0-9-]+)"?', PROJECT_ENV.read_text(), re.M)
    if not m:
        raise SystemExit("deploy/project.env has no PROJECT_ID")
    return m.group(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--database", default="(default)")
    ap.add_argument("--yes", action="store_true", help="actually delete (otherwise only count)")
    a = ap.parse_args()
    if a.project != _allowed_project():
        print(f"Refusing: only {_allowed_project()} (deploy/project.env) can be reset.", file=sys.stderr)
        return 2

    from google.cloud import firestore
    from google.cloud.firestore_v1.base_query import FieldFilter

    db = firestore.Client(project=a.project, database=a.database)
    cases = list(db.collection("cases").where(filter=FieldFilter("synthetic", "==", True)).stream())
    real = int(db.collection("cases").where(filter=FieldFilter("synthetic", "==", False)).count().get()[0][0].value)
    print(f"{len(cases)} SIMULATED cases to delete; {real} real cases kept.")
    if not a.yes:
        print("Dry run. Add --yes to delete.")
        return 0
    batch, ops, deleted = db.batch(), 0, 0
    for snap in cases:
        for ev in snap.reference.collection("events").select([]).stream():
            batch.delete(ev.reference)
            ops += 1
            if ops >= 450:
                batch.commit()
                batch, ops = db.batch(), 0
        batch.delete(snap.reference)
        ops += 1
        deleted += 1
        if ops >= 450:
            batch.commit()
            batch, ops = db.batch(), 0
    if ops:
        batch.commit()
    db.collection("meta").document("clock").set({"offset_days": 0, "reset": True})
    print(f"Deleted {deleted} SIMULATED cases and their events. Demo clock reset to today.")
    print("The API picks up the reset clock within 30 seconds. Then reseed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
