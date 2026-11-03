"""Versioned identity-domain contracts, independent of transport or login."""
from dataclasses import dataclass
from typing import Literal

Role = Literal["owner", "admin", "editor", "viewer"]
MembershipState = Literal["ACTIVE", "SUSPENDED"]
ROLES = frozenset(("owner", "admin", "editor", "viewer"))
MEMBERSHIP_STATES = frozenset(("ACTIVE", "SUSPENDED"))


@dataclass(frozen=True)
class LegacyBinding:
    """Local owner alias mapping. Do not treat an alias as verified identity."""
    alias: str
    user_id: str
    workspace_id: str


@dataclass(frozen=True)
class WorkspaceMembership:
    workspace_id: str
    user_id: str
    role: Role
    state: MembershipState
