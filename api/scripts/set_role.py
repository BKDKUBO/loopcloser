"""Set a LoopCloser role on a Firebase Auth user (custom claim "role").

Run by an admin with Application Default Credentials:
  python scripts/set_role.py user@example.com coordinator
"""

import sys

import firebase_admin
from firebase_admin import auth

ROLES = {"worker", "coordinator", "supervisor", "program_manager", "patient"}

if len(sys.argv) != 3 or sys.argv[2] not in ROLES:
    sys.exit(f"usage: set_role.py <email> <{'|'.join(sorted(ROLES))}>")
firebase_admin.initialize_app()
user = auth.get_user_by_email(sys.argv[1])
auth.set_custom_user_claims(user.uid, {"role": sys.argv[2]})
print(f"{sys.argv[1]} -> {sys.argv[2]} (user must sign in again to refresh the token)")
