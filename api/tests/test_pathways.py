def test_all_pathways_pending_signoff_and_cited(lib):
    for p in lib.all():
        assert p.signoff_status == "pending_clinical_signoff"
        assert p.deadline_label == "configurable default, pending clinical review"
        assert p.sources and all(s.startswith("https://") for s in p.sources)


def test_must_pathways_present(lib):
    ids = {p.id for p in lib.latest() if p.scope == "MUST"}
    assert ids == {"abnormal-generic", "borderline", "fit-positive", "bp-elevated"}


def test_published_versions_are_immutable(lib):
    assert lib.lock_mismatches() == []


def test_matching_prefers_specific(lib):
    assert lib.match("fit", "positive", "abnormal").id == "fit-positive"
    assert lib.match("generic", "abnormal", "abnormal").id == "abnormal-generic"
    assert lib.match("bp", "borderline", "borderline").id == "borderline"
    assert lib.match("bp", "elevated", "abnormal").id == "bp-elevated"
    assert lib.match("generic", "normal", "normal") is None


def test_bp_uses_who_threshold_and_no_invented_red_flag_number(lib):
    p = lib.get("bp-elevated")
    assert p.parameters["confirm_systolic_mmhg"] == 140 and p.parameters["confirm_diastolic_mmhg"] == 90
    assert p.parameters["very_high_threshold"] is None


def test_changed_file_is_detected(tmp_path, lib):
    import json
    import shutil

    from loopcloser.pathways.library import DATA_DIR, LOCK_PATH, PathwayLibrary

    d = tmp_path / "data"
    shutil.copytree(DATA_DIR, d)
    f = d / "borderline@1.0.0.json"
    doc = json.loads(f.read_text())
    doc["default_deadline_days"] = 5
    f.write_text(json.dumps(doc))
    assert any("borderline@1.0.0" in m for m in PathwayLibrary(d).lock_mismatches(LOCK_PATH))
