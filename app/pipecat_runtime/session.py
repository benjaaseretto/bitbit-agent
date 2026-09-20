"""Compat: reexporta sesión desde app.session."""
from app.session.call_session import CallSession
from app.session import BitbitSession

__all__ = ["BitbitSession", "CallSession"]
