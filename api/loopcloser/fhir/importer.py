"""Map a FHIR R4 Bundle (Patient + Observation / DiagnosticReport, optionally ServiceRequest) to screenings.

This is the one place that reads FHIR. It never calls a FHIR server: the Bundle is pasted by a coordinator or
loaded from the built-in SYNTHETIC sample. Rules:

- Only final results are imported (status final, amended or corrected). Preliminary ones are reported, not opened.
- LoopCloser never interprets raw values. The sending lab's interpretation code decides (HL7 v3
  ObservationInterpretation: POS, DET, A, H, HH, L, LL, AA, N, NEG, ND). A result with no interpretation is an
  error for that result, not a guess.
- Normal results (N, NEG, ND) do not open a case, the same as the CSV import.
- Names, phone numbers and addresses in the Bundle are never stored. The Patient's identifier (or id) becomes the
  pseudonymous participant id; a phone number only sets "phone on file" (yes or no).
- Consent to contact is never inferred from a Bundle: imported cases start with consent "not recorded", so calls
  and SMS hold until a person records it (rule GATE-1).
- The LOINC table is short and pending clinical review. Unknown codes go to the generic pathway, flagged.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

LOINC = "http://loinc.org"
V3_INTERP = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"
MAX_ENTRIES = 50
MAX_BYTES = 256 * 1024
BUNDLE_TYPES = {"collection", "transaction", "batch", "message", "searchset", "document"}
FINAL = {"final", "amended", "corrected"}
SYNTHETIC_TAGS = {"synthetic", "simulated", "SIMULATED"}

# LOINC code -> (screening_type, display). Checked against the NLM LOINC search (clinicaltables.nlm.nih.gov) on
# 2026-11-19. Pending clinical review, like every pathway.
LOINC_TABLE: dict[str, tuple[str, str]] = {
    "29771-3": ("fit", "Hemoglobin [Presence] in Stool from gastrointestinal lower by Immunoassay"),
    "57905-2": ("fit", "Hemoglobin [Presence] in Stool from gastrointestinal lower by Immunoassay --1st specimen"),
    "85354-9": ("bp", "Blood pressure panel with all children optional"),
    "55284-4": ("bp", "Blood pressure systolic and diastolic"),
    "8480-6": ("bp", "Systolic blood pressure"),
    "8462-4": ("bp", "Diastolic blood pressure"),
    "21440-3": ("cervical", "Human papilloma virus 16+18+31+33+35+45+51+52+56 DNA [Presence] in Cervix by Probe"),
    "30167-1": (
        "cervical",
        "Human papilloma virus high risk DNA [Presence] in Cervix by Probe with signal amplification",
    ),
    "59263-4": ("cervical", "Human papilloma virus 16 DNA [Presence] in Cervix by Probe with signal amplification"),
    "77379-6": ("cervical", "Human papilloma virus DNA [Interpretation] in Cervix"),
    "10524-7": ("cervical", "Microscopic observation [Identifier] in Cervix by Cyto stain"),
}
# Interpretation code -> (kind, severity). kind: positive | abnormal | normal.
INTERP: dict[str, tuple[str, str]] = {
    "POS": ("positive", "abnormal"),
    "DET": ("positive", "abnormal"),
    "A": ("abnormal", "abnormal"),
    "H": ("abnormal", "abnormal"),
    "L": ("abnormal", "abnormal"),
    "HU": ("abnormal", "abnormal"),
    "LU": ("abnormal", "abnormal"),
    "AA": ("abnormal", "critical"),
    "HH": ("abnormal", "critical"),
    "LL": ("abnormal", "critical"),
    "N": ("normal", "normal"),
    "NEG": ("normal", "normal"),
    "ND": ("normal", "normal"),
}
_RANK = {"normal": 0, "abnormal": 1, "critical": 2}
LANGS = {"en": "en", "en-PH": "en", "en-US": "en", "fil": "fil", "tl": "fil", "fil-PH": "fil", "tl-PH": "fil"}
_PID_RE = re.compile(r"[^A-Za-z0-9-]")
PHONE_OK = re.compile(r"^\+639\d{9}$")


class BundleError(ValueError):
    """The Bundle as a whole cannot be read."""


@dataclass
class Mapped:
    """One result ready to open as a case (or the reason it is not)."""

    resource: str  # e.g. "DiagnosticReport/fit-1"
    case_id: str | None = None
    screening: dict[str, Any] | None = None
    source: dict[str, Any] | None = None
    referral: str | None = None
    status: str = "ready"  # ready | skipped | error
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"resource": self.resource, "status": self.status, "messages": self.messages}
        if self.case_id:
            out["case_id"] = self.case_id
        if self.screening:
            out["screening_type"] = self.screening["screening_type"]
            out["result"] = self.screening["result"]
            out["severity"] = self.screening["severity"]
            out["screened_at"] = self.screening["screened_at"]
        if self.source:
            out["code"] = self.source.get("code")
            out["interpretation"] = self.source.get("interpretation")
        if self.referral:
            out["referral"] = self.referral
        return out


@dataclass
class ImportPlan:
    bundle_id: str | None
    synthetic: bool
    items: list[Mapped]
    warnings: list[str]

    @property
    def ready(self) -> list[Mapped]:
        return [m for m in self.items if m.status == "ready"]


def _refs(entry: dict[str, Any]) -> list[str]:
    r = entry.get("resource") or {}
    out = []
    if entry.get("fullUrl"):
        out.append(str(entry["fullUrl"]))
    if r.get("id"):
        out.append(f"{r.get('resourceType')}/{r['id']}")
    return out


def _codings(cc: Any) -> list[dict[str, Any]]:
    if isinstance(cc, dict):
        return [c for c in cc.get("coding") or [] if isinstance(c, dict)]
    if isinstance(cc, list):
        return [c for x in cc for c in _codings(x)]
    return []


def _interp_codes(cc: Any) -> list[str]:
    return [str(c.get("code")) for c in _codings(cc) if c.get("code") and (c.get("system") in (V3_INTERP, None))]


def _loinc(res: dict[str, Any]) -> tuple[str | None, str | None]:
    for c in _codings(res.get("code")):
        if c.get("system") == LOINC and c.get("code"):
            return str(c["code"]), c.get("display")
    text = (res.get("code") or {}).get("text") if isinstance(res.get("code"), dict) else None
    return None, text


def _date(res: dict[str, Any]) -> date | None:
    for k in ("effectiveDateTime", "issued"):
        v = res.get(k)
        if v:
            try:
                return date.fromisoformat(str(v)[:10])
            except ValueError:
                return None
    period = res.get("effectivePeriod") or {}
    if period.get("start"):
        try:
            return date.fromisoformat(str(period["start"])[:10])
        except ValueError:
            return None
    return None


def _participant(patient: dict[str, Any]) -> str:
    raw = ""
    for ident in patient.get("identifier") or []:
        if isinstance(ident, dict) and ident.get("value"):
            raw = str(ident["value"])
            break
    raw = raw or str(patient.get("id") or "")
    clean = _PID_RE.sub("", raw)[:32]
    return f"FHIR-{clean}" if clean else ""


def _language(patient: dict[str, Any]) -> str:
    for comm in patient.get("communication") or []:
        for c in _codings((comm or {}).get("language")):
            if c.get("code") in LANGS:
                return LANGS[c["code"]]
    return "en"


def _phone_valid(patient: dict[str, Any]) -> bool:
    for t in patient.get("telecom") or []:
        if (
            isinstance(t, dict)
            and t.get("system") == "phone"
            and PHONE_OK.match(str(t.get("value", "")).replace(" ", ""))
        ):
            return True
    return False


def _age_band(patient: dict[str, Any], today: date) -> str | None:
    try:
        born = date.fromisoformat(str(patient.get("birthDate"))[:10])
    except ValueError:
        return None
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if age < 0 or age > 120:
        return None
    lo = (age // 10) * 10
    return f"{lo}-{lo + 9}"


def _case_id(participant: str, resource: str, when: date) -> str:
    h = hashlib.sha256(f"{participant}|{resource}|{when.isoformat()}".encode()).hexdigest()[:10].upper()
    return f"C-FHIR-{h}"


def plan_import(bundle: Any, *, today: date) -> ImportPlan:
    """Validate a Bundle and map each final result to a screening. Raises BundleError for an unreadable Bundle."""
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise BundleError('Not a FHIR Bundle: "resourceType" must be "Bundle".')
    if bundle.get("type") not in BUNDLE_TYPES:
        raise BundleError(f"Bundle.type must be one of {', '.join(sorted(BUNDLE_TYPES))}.")
    entries = bundle.get("entry")
    if not isinstance(entries, list) or not entries:
        raise BundleError("The Bundle has no entries.")
    if len(entries) > MAX_ENTRIES:
        raise BundleError(f"Too many entries ({len(entries)}). At most {MAX_ENTRIES} per import.")
    tags = {str(t.get("code")) for t in (bundle.get("meta") or {}).get("tag") or [] if isinstance(t, dict)}
    synthetic = bool(tags & SYNTHETIC_TAGS)
    warnings: list[str] = []
    if not synthetic:
        warnings.append(
            "This Bundle is not tagged synthetic. This is a public demo: paste synthetic data only. "
            "Names, phones and addresses are never stored either way."
        )

    by_ref: dict[str, dict[str, Any]] = {}
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get("resource"), dict):
            raise BundleError("Every entry needs a resource.")
        for ref in _refs(e):
            by_ref[ref] = e["resource"]
    resources = [e["resource"] for e in entries]
    kinds = {r.get("resourceType") for r in resources}
    if "Patient" not in kinds:
        raise BundleError("The Bundle needs a Patient resource.")
    if not kinds & {"Observation", "DiagnosticReport"}:
        raise BundleError("The Bundle needs at least one Observation or DiagnosticReport.")
    ignored = sorted(k for k in kinds - {"Patient", "Observation", "DiagnosticReport", "ServiceRequest"} if k)
    if ignored:
        warnings.append(f"Ignored resource types: {', '.join(ignored)}.")

    def resolve(ref: Any) -> dict[str, Any] | None:
        if isinstance(ref, dict):
            ref = ref.get("reference")
        return by_ref.get(str(ref)) if ref else None

    referrals: dict[str, str] = {}
    for r in resources:
        if r.get("resourceType") == "ServiceRequest":
            subj = resolve(r.get("subject"))
            text = (r.get("code") or {}).get("text") or next(
                (c.get("display") for c in _codings(r.get("code")) if c.get("display")), None
            )
            if subj is not None and text:
                referrals[id(subj)] = str(text)[:200]  # type: ignore[index]

    in_report: set[int] = set()
    for r in resources:
        if r.get("resourceType") == "DiagnosticReport":
            for ref in r.get("result") or []:
                obs = resolve(ref)
                if obs is not None:
                    in_report.add(id(obs))

    items: list[Mapped] = []
    for r in resources:
        rt = r.get("resourceType")
        if rt not in {"Observation", "DiagnosticReport"} or (rt == "Observation" and id(r) in in_report):
            continue
        label = f"{rt}/{r.get('id') or '?'}"
        m = Mapped(resource=label)
        items.append(m)
        status = r.get("status")
        if status not in FINAL:
            m.status = "skipped"
            m.messages.append(f'Status is "{status}". Only final results are imported.')
            continue
        patient = resolve(r.get("subject"))
        if patient is None or patient.get("resourceType") != "Patient":
            m.status = "error"
            m.messages.append("subject must reference a Patient in this Bundle.")
            continue
        pid = _participant(patient)
        if not pid:
            m.status = "error"
            m.messages.append("The Patient needs an identifier or an id.")
            continue
        when = _date(r)
        if when is None:
            m.status = "error"
            m.messages.append("No result date (effectiveDateTime or issued, YYYY-MM-DD).")
            continue
        if when > today:
            m.status = "error"
            m.messages.append(f"Result date {when.isoformat()} is in the future.")
            continue
        if when < today - timedelta(days=365):
            m.messages.append(f"Result date {when.isoformat()} is more than a year old.")
        code, display = _loinc(r)
        interp = _interp_codes(r.get("interpretation")) + _interp_codes(r.get("conclusionCode"))
        if rt == "DiagnosticReport":
            for ref in r.get("result") or []:
                obs = resolve(ref)
                if obs is not None:
                    interp += _interp_codes(obs.get("interpretation"))
                    if code is None:
                        code, display = _loinc(obs)
        known = [INTERP[c] for c in interp if c in INTERP]
        if not known:
            m.status = "error"
            m.messages.append(
                "No interpretation code (e.g. POS, A, H, N). LoopCloser does not interpret raw values; "
                "the sending lab must flag the result."
            )
            continue
        kind, severity = max(known, key=lambda k: _RANK[k[1]])
        if severity == "normal":
            m.status = "skipped"
            m.messages.append("Normal result: no follow-up case is opened.")
            continue
        if code in LOINC_TABLE:
            stype, display = LOINC_TABLE[code][0], LOINC_TABLE[code][1]
        else:
            stype = "generic"
            m.messages.append(
                f"Code {code or display or 'missing'} is not in the LOINC table: generic follow-up pathway, "
                "a person reviews it."
            )
        result = {"fit": "positive", "bp": "elevated", "cervical": kind}.get(stype, "abnormal")
        m.case_id = _case_id(pid, label, when)
        m.referral = referrals.get(id(patient))  # type: ignore[call-overload]
        m.screening = {
            "participant_id": pid,
            "screening_id": f"FHIR-{label.replace('/', '-')}"[:60],
            "screening_type": stype,
            "result": result,
            "severity": severity,
            "screened_at": when.isoformat(),
            "language": _language(patient),
            "age_band": _age_band(patient, today),
            "phone_valid": _phone_valid(patient),
            "contact_consent": None,  # never inferred from a Bundle (rule GATE-1)
            "red_flag": False,
        }
        m.source = {
            "kind": "fhir_r4_bundle",
            "bundle_id": str(bundle.get("id") or "")[:64] or None,
            "resource": label,
            "code": f"LOINC {code}" if code else None,
            "display": (display or "")[:160] or None,
            "interpretation": ",".join(sorted(set(interp)))[:40],
            "synthetic": synthetic,
        }
    return ImportPlan(bundle_id=bundle.get("id"), synthetic=synthetic, items=items, warnings=warnings)


SAMPLE_KINDS = ("fit", "cervical", "bp")


def sample_bundle(kind: str = "fit", *, today: date, seed: str | None = None) -> dict[str, Any]:
    """A SYNTHETIC FHIR R4 collection Bundle. A fresh patient identifier each call, so every press opens a new
    case. Fictional: the name says SIMULATED and the phone uses the fake +63 9000 range the demo never texts."""
    s = seed or uuid.uuid4().hex[:8].upper()
    pid, when = f"SIM-{s}", (today - timedelta(days=2)).isoformat()
    patient = {
        "resourceType": "Patient",
        "id": f"pat-{s.lower()}",
        "meta": {"tag": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActReason", "code": "HTEST"}]},
        "identifier": [{"system": "urn:loopcloser:demo:participant", "value": pid}],
        "name": [{"text": "SIMULATED Patient"}],
        "telecom": [{"system": "phone", "value": "+639000199999", "use": "mobile"}],
        "gender": "female",
        "birthDate": f"{today.year - 54}-03-14",
        "communication": [{"language": {"coding": [{"system": "urn:ietf:bcp:47", "code": "fil"}]}}],
    }
    pref = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'pat' + s)}"
    oref = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'obs' + s)}"
    code, display, interp, conclusion = {
        "fit": (
            "29771-3",
            "Hemoglobin [Presence] in Stool from gastrointestinal lower by Immunoassay",
            "POS",
            "Positive faecal immunochemical test (SIMULATED)",
        ),
        "cervical": (
            "30167-1",
            "Human papilloma virus high risk DNA [Presence] in Cervix by Probe",
            "POS",
            "High-risk HPV detected (SIMULATED)",
        ),
        "bp": (
            "85354-9",
            "Blood pressure panel with all children optional",
            "H",
            "Blood pressure above the screening threshold (SIMULATED)",
        ),
    }[kind]
    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"obs-{s.lower()}",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory" if kind != "bp" else "vital-signs",
                    }
                ]
            }
        ],
        "code": {"coding": [{"system": LOINC, "code": code, "display": display}]},
        "subject": {"reference": pref},
        "effectiveDateTime": when,
        "interpretation": [{"coding": [{"system": V3_INTERP, "code": interp}]}],
    }
    if kind == "bp":
        obs["component"] = [
            {
                "code": {"coding": [{"system": LOINC, "code": "8480-6", "display": "Systolic blood pressure"}]},
                "valueQuantity": {
                    "value": 152,
                    "unit": "mmHg",
                    "system": "http://unitsofmeasure.org",
                    "code": "mm[Hg]",
                },
            },
            {
                "code": {"coding": [{"system": LOINC, "code": "8462-4", "display": "Diastolic blood pressure"}]},
                "valueQuantity": {"value": 96, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
            },
        ]
    else:
        obs["valueCodeableConcept"] = {
            "coding": [{"system": "http://snomed.info/sct", "code": "10828004", "display": "Positive"}]
        }
    report = {
        "resourceType": "DiagnosticReport",
        "id": f"rep-{s.lower()}",
        "status": "final",
        "code": {"coding": [{"system": LOINC, "code": code, "display": display}]},
        "subject": {"reference": pref},
        "effectiveDateTime": when,
        "issued": f"{when}T09:00:00+08:00",
        "result": [{"reference": oref}],
        "conclusion": conclusion,
    }
    referral = {
        "fit": "Referral for colonoscopy",
        "cervical": "Referral for colposcopy",
        "bp": "Repeat blood pressure check at the health center",
    }[kind]
    service_request = {
        "resourceType": "ServiceRequest",
        "id": f"sr-{s.lower()}",
        "status": "active",
        "intent": "order",
        "code": {"text": referral},
        "subject": {"reference": pref},
        "authoredOn": when,
    }
    return {
        "resourceType": "Bundle",
        "id": f"loopcloser-sample-{kind}-{s.lower()}",
        "meta": {
            "tag": [{"system": "urn:loopcloser:data-label", "code": "SIMULATED"}],
            "lastUpdated": f"{when}T09:05:00+08:00",
        },
        "type": "collection",
        "timestamp": datetime.fromisoformat(f"{when}T09:05:00+08:00").isoformat(),
        "entry": [
            {"fullUrl": pref, "resource": patient},
            {"fullUrl": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'rep' + s)}", "resource": report},
            {"fullUrl": oref, "resource": obs},
            {"fullUrl": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'sr' + s)}", "resource": service_request},
        ],
    }
