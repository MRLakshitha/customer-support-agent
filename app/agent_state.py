"""Session state, confirmation gates, and escalation rules."""

from dataclasses import dataclass, field
from threading import RLock
from typing import Any
import re


@dataclass
class SessionState:
    session_id: str
    customer_id: str
    context: list[dict[str, Any]] = field(default_factory=list)
    pending_action: dict[str, Any] | None = None
    clarification_attempts: int = 0
    unresolved_complaint_count: int = 0
    consecutive_tool_failures: dict[str, int] = field(default_factory=dict)
    escalated: bool = False


class SessionStore:
    """Keeps conversation and confirmation state isolated per session."""

    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
        self._lock = RLock()

    def get_or_create(self, session_id: str, customer_id: str) -> SessionState:
        if not isinstance(session_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,100}", session_id
        ):
            raise ValueError("Invalid session ID.")

        if not isinstance(customer_id, str) or not re.fullmatch(
            r"CUST-\d{3}", customer_id
        ):
            raise ValueError("Invalid customer ID.")

        with self._lock:
            existing = self._sessions.get(session_id)

            if existing:
                if existing.customer_id != customer_id:
                    raise PermissionError(
                        "Session is already associated with another customer."
                    )
                return existing

            state = SessionState(
                session_id=session_id,
                customer_id=customer_id,
            )
            self._sessions[session_id] = state
            return state

    def set_pending_action(
        self,
        state: SessionState,
        action: str,
        order_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if action not in {"CANCEL_ORDER", "RETURN_REQUEST"}:
            raise ValueError("Unsupported confirmation action.")

        if not re.fullmatch(r"ORD-\d{4}", order_id):
            raise ValueError("Invalid order ID.")

        with self._lock:
            state.pending_action = {
                "action": action,
                "order_id": order_id,
                "details": details or {},
                "confirmed": False,
            }

    def confirm_pending_action(self, state: SessionState) -> dict[str, Any] | None:
        """Record confirmation once and return a copy of the pending action."""
        with self._lock:
            pending = state.pending_action

            if not pending or pending["confirmed"]:
                return None

            pending["confirmed"] = True
            return {
                **pending,
                "details": dict(pending["details"]),
            }

    def clear_pending_action(self, state: SessionState) -> None:
        with self._lock:
            state.pending_action = None

    def record_tool_success(self, state: SessionState, tool_name: str) -> None:
        state.consecutive_tool_failures[tool_name] = 0

    def record_tool_failure(
        self, state: SessionState, tool_name: str
    ) -> dict[str, str] | None:
        failures = state.consecutive_tool_failures.get(tool_name, 0) + 1
        state.consecutive_tool_failures[tool_name] = failures

        if failures >= 3:
            return {
                "trigger": "TOOL_FAILURE",
                "severity": "MEDIUM",
                "message": (
                    f"The {tool_name} tool failed three consecutive times. "
                    "Human support is required."
                ),
            }
        return None


def detect_escalation(
    message: str,
    state: SessionState,
    *,
    refund_amount: int | float | None = None,
    confidence: float | None = None,
) -> dict[str, str] | None:
    """Apply deterministic escalation rules."""
    text = message.casefold()

    if re.search(r"\b(human|real person|live agent|customer service agent|human agent|manager|supervisor)\b", text):
        return {"trigger": "HUMAN_REQUESTED", "severity": "HIGH", "message": "The customer requested human support."}

    if re.search(r"\b(fraud|payment dispute|account hacked|account security|account compromised)\b", text):
        return {"trigger": "LOW_CONFIDENCE", "severity": "LOW", "message": "This security or payment issue requires human support."}

    if re.search(r"\b(lawyer|lawsuit|legal action|chargeback|threaten|threatening|scamming me|report you publicly|social media complaint)\b", text):
        return {"trigger": "HIGH_DISSATISFACTION", "severity": "HIGH", "message": "The message requires human review."}

    if refund_amount is not None and refund_amount > 10000:
        return {"trigger": "REFUND_OVER_LIMIT", "severity": "MEDIUM", "message": "The requested refund exceeds INR 10,000. Do not create the return; refer to human support."}

    if state.unresolved_complaint_count >= 3:
        return {"trigger": "HIGH_DISSATISFACTION", "severity": "HIGH", "message": "The same unresolved complaint has been repeated."}

    if state.clarification_attempts >= 2 and (confidence is None or confidence < 0.5):
        return {"trigger": "LOW_CONFIDENCE", "severity": "LOW", "message": "The request remains unclear after two clarifications."}

    return None


def record_event(
    state: SessionState,
    event_type: str,
    **details: Any,
) -> dict[str, Any]:
    """Record a structured event without credentials or hidden prompts."""
    event = {
        "event": event_type,
        "session_id": state.session_id,
        "customer_id": state.customer_id,
        **details,
    }
    state.context.append(event)
    return event
