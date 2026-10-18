"""Roles and the permission matrix (PLAN_FINAL.md section 9)."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    WORKER = "worker"  # community / care worker
    COORDINATOR = "coordinator"
    SUPERVISOR = "supervisor"
    PROGRAM_MANAGER = "program_manager"
    PATIENT = "patient"
    SYSTEM = "system"  # internal: scheduler, importer. Never assigned to a person.


STAFF_ROLES = frozenset({Role.WORKER, Role.COORDINATOR, Role.SUPERVISOR, Role.PROGRAM_MANAGER})
HUMAN_ROLES = STAFF_ROLES | {Role.PATIENT}


class Perm(StrEnum):
    CASE_READ_ASSIGNED = "case:read_assigned"
    CASE_READ_ALL = "case:read_all"
    CASE_READ_OWN = "case:read_own"  # patient: only their own case
    CASE_OPEN = "case:open"
    CASE_ASSIGN = "case:assign"
    CASE_TRANSITION = "case:transition"
    CASE_CONTACT = "case:contact"
    CASE_CLOSE = "case:close"
    CASE_NOTE = "case:note"
    RED_FLAG_REPORT = "red_flag:report"
    RED_FLAG_RESOLVE = "red_flag:resolve"
    AUTOMATION_RESUME = "automation:resume"
    EVENTS_READ = "events:read"
    AUDIT_READ = "audit:read"
    IMPORT_CSV = "import:csv"
    PATHWAY_READ = "pathway:read"
    DASHBOARD_READ = "dashboard:read"
    PATIENT_RESPOND = "patient:respond"
    PRIORITY_OVERRIDE = "priority:override"
    MESSAGE_SEND = "message:send"
    ADMIN = "admin"  # rebuild projections, seed demo data


_WORKER = {
    Perm.CASE_READ_ASSIGNED,
    Perm.CASE_TRANSITION,
    Perm.CASE_CONTACT,
    Perm.CASE_NOTE,
    Perm.RED_FLAG_REPORT,
    Perm.EVENTS_READ,
    Perm.PATHWAY_READ,
    Perm.MESSAGE_SEND,
}
_COORDINATOR = _WORKER | {
    Perm.CASE_READ_ALL,
    Perm.CASE_OPEN,
    Perm.CASE_ASSIGN,
    Perm.CASE_CLOSE,
    Perm.RED_FLAG_RESOLVE,
    Perm.IMPORT_CSV,
    Perm.DASHBOARD_READ,
}
_SUPERVISOR = _COORDINATOR | {Perm.AUTOMATION_RESUME, Perm.AUDIT_READ, Perm.ADMIN, Perm.PRIORITY_OVERRIDE}
_PROGRAM_MANAGER = {
    Perm.CASE_READ_ALL,
    Perm.EVENTS_READ,
    Perm.AUDIT_READ,
    Perm.PATHWAY_READ,
    Perm.DASHBOARD_READ,
}
_PATIENT = {Perm.CASE_READ_OWN, Perm.PATIENT_RESPOND, Perm.RED_FLAG_REPORT}

PERMISSIONS: dict[Role, frozenset[Perm]] = {
    Role.WORKER: frozenset(_WORKER),
    Role.COORDINATOR: frozenset(_COORDINATOR),
    Role.SUPERVISOR: frozenset(_SUPERVISOR),
    Role.PROGRAM_MANAGER: frozenset(_PROGRAM_MANAGER),
    Role.PATIENT: frozenset(_PATIENT),
    Role.SYSTEM: frozenset(),
}

# Roles allowed to sign off a closure (guard rule CLOSE-2).
CLOSE_SIGNOFF_ROLES = frozenset({Role.COORDINATOR, Role.SUPERVISOR})


def has_perm(role: Role, perm: Perm) -> bool:
    return perm in PERMISSIONS.get(role, frozenset())
