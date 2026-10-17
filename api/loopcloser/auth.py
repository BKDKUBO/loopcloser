"""Authentication and role-based authorization.

firebase mode: the web app signs in with Firebase Auth and sends the ID token as
  "Authorization: Bearer <token>". We verify it with the Firebase Admin SDK and read
  the role from the custom claim "role" (set with scripts/set_role.py).
demo mode (local and the judged demo only): a role switcher sends X-Demo-Role and
  X-Demo-User. Refused in production unless ALLOW_DEMO_AUTH_IN_PRODUCTION=true.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from .config import get_config
from .domain.events import Actor
from .domain.roles import HUMAN_ROLES, Perm, Role, has_perm


@dataclass(frozen=True)
class Principal:
    uid: str
    role: Role
    email: str | None = None
    demo: bool = False

    @property
    def actor(self) -> Actor:
        return Actor(id=self.uid, role=self.role, kind="human")


TokenVerifier = Callable[[str], dict]
_verifier: TokenVerifier | None = None


def _firebase_verifier(token: str) -> dict:
    import firebase_admin
    from firebase_admin import auth as fb_auth

    if not firebase_admin._apps:
        cfg = get_config()
        firebase_admin.initialize_app(options={"projectId": cfg.firebase_project} if cfg.firebase_project else None)
    return fb_auth.verify_id_token(token)


def set_token_verifier(fn: TokenVerifier | None) -> None:
    """Tests inject a fake verifier here."""
    global _verifier
    _verifier = fn


def _parse_role(value: str | None) -> Role:
    try:
        role = Role(value or "")
    except ValueError:
        raise HTTPException(status_code=403, detail="No LoopCloser role on this account.") from None
    if role not in HUMAN_ROLES:
        raise HTTPException(status_code=403, detail="Invalid role.")
    return role


def authenticate(request: Request) -> Principal:
    cfg = get_config()
    if cfg.auth_mode == "demo":
        role = _parse_role(request.headers.get("x-demo-role"))
        uid = (request.headers.get("x-demo-user") or f"demo-{role.value}")[:64]
        return Principal(uid=uid, role=role, demo=True)

    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in required.", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = (_verifier or _firebase_verifier)(header[7:].strip())
    except Exception:  # noqa: BLE001  any verification failure is a 401
        raise HTTPException(status_code=401, detail="Invalid or expired sign-in.") from None
    return Principal(
        uid=claims["uid"] if "uid" in claims else claims["sub"],
        role=_parse_role(claims.get("role")),
        email=claims.get("email"),
    )


def current_user(request: Request) -> Principal:
    p = authenticate(request)
    request.state.principal = p
    return p


def require(*perms: Perm):
    def dep(p: Principal = Depends(current_user)) -> Principal:
        missing = [x for x in perms if not has_perm(p.role, x)]
        if missing:
            raise HTTPException(status_code=403, detail=f"Your role ({p.role.value}) cannot do this.")
        return p

    return dep
