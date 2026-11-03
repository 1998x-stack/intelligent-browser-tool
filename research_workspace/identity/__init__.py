"""Internal identity/workspace persistence, NOT an authentication provider.

V04-01 provides local placeholder migration and guarded membership storage.
No HTTP routes, login sessions, invitations, or token issuance are provided.
"""
from .repository import WorkspaceRepository
from .models import ROLES, MEMBERSHIP_STATES

__all__ = ["WorkspaceRepository", "ROLES", "MEMBERSHIP_STATES"]
