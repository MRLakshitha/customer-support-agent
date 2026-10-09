"""Deterministic customer support agent orchestration."""

import logging
import re

from app import mock_backend as backend
from app.agent_state import SessionStore, detect_escalation

logger = logging.getLogger("customer_support.agent")

POLICY = {
    "shipping": "Orders arrive 3â€“5 business days after dispatch.",
    "cancellation": "Orders can only be cancelled before shipment.",
    "returns": (
        "Returns are accepted within 7 days of delivery for unused items "
        "in original packaging. Gift cards and digital products are non-returnable."
    ),
    "refunds": "Approved refunds take 5â€“7 business days after the item is received.",
    "support": "Human support is available Mondayâ€“Saturday, 09:00â€“18:00 IST.",
}

ORDER_ID = re.compile(r"\bORD-\d{4}\b", re.I)
PRODUCT_ID = re.compile(r"\bPRD-\d{3}\b", re.I)

sessions = SessionStore()


def _log(event, state, **details):
    logger.info(
        "%s",
        {
            "event": event,
            "session_id": state.session_id,
            "customer_id": state.customer_id,
            **details,
        },
    )


def _run_tool(state, name, function, *args):
    """Retry a failing tool up to three total attempts."""
    for attempt in range(1, 4):
        try:
            result = function(*args)
            sessions.record_tool_success(state, name)
            _log("tool_success", state, tool=name, attempt=attempt)
            return result
        except Exception as exc:
            sessions.record_tool_failure(state, name)
            _log(
                "tool_failure",
                state,
                tool=name,
                attempt=attempt,
                error_type=type(exc).__name__,
            )
            if attempt == 3:
                state.escalated = True
                return {
                    "success": False,
                    "escalation": {
                        "trigger": "TOOL_FAILURE",
                        "severity": "MEDIUM",
                    },
                    "message": (
                        "I'm unable to complete that request because the "
                        "service failed repeatedly. Please contact human support."
                    ),
                }
    return {"success": False, "message": "Tool execution failed."}


def _finish_confirmation(state, message):
    """Only a customer's explicit message can confirm a pending action."""
    pending = state.pending_action
    if not pending:
        return None

    text = message.strip().casefold()

    yes = bool(re.fullmatch(
        r"(yes|yes please|confirm|confirmed|proceed|do it|go ahead|"
        r"i confirm|please proceed)[.! ]*",
        text,
    ))
    no = bool(re.fullmatch(
        r"(no|no thanks|cancel that|don't do it|do not proceed|"
        r"stop|not now)[.! ]*",
        text,
    ))

    if not yes and not no:
        return {
            "reply": (
                "Please reply 'yes' to confirm or 'no' to cancel this action."
            ),
            "intent": pending["action"],
            "awaiting_confirmation": True,
        }

    if no:
        sessions.clear_pending_action(state)
        return {
            "reply": "Okay, I haven't made any changes.",
            "intent": pending["action"],
            "success": False,
        }

    action = sessions.confirm_pending_action(state)
    if action is None:
        return {
            "reply": "There is no unconfirmed action to execute.",
            "success": False,
        }

    order_id = action["order_id"]
    details = action["details"]

    if action["action"] == "CANCEL_ORDER":
        result = _run_tool(
            state, "cancel_order", backend.cancel_order,
            order_id, state.customer_id, True,
        )
        sessions.clear_pending_action(state)
        return {
            "reply": (
                f"Order {order_id} has been cancelled."
                if result.get("success")
                else result.get("message", result.get("reason", "Cancellation failed."))
            ),
            "intent": "CANCEL_ORDER",
            "success": result.get("success", False),
            "result": result,
        }

    result = _run_tool(
        state, "create_return", backend.create_return,
        order_id, state.customer_id, details["reason"], True,
    )
    sessions.clear_pending_action(state)
    return {
        "reply": (
            f"Return request {result['return_id']} was created for {order_id}."
            if result.get("success") and "return_id" in result
            else result.get("message", result.get("reason", "Return creation failed."))
        ),
        "intent": "RETURN_REQUEST",
        "success": result.get("success", False),
        "result": result,
    }


def _handle_message(session_id, customer_id, message):
    """Handle one customer message and return a structured response."""
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        return {"reply": "Please provide a valid message.", "intent": "GENERAL_QUESTION"}

    state = sessions.get_or_create(session_id, customer_id)
    text = message.strip()
    lowered = text.casefold()

    logger.info(
        "%s",
        {
            "event": "message_received",
            "session_id": session_id,
            "customer_id": customer_id,
        },
    )

    # Handle an existing confirmation before classifying a new request.
    if state.pending_action:
        pending = state.pending_action
        if pending["action"] == "RETURN_REQUEST" and not pending["details"].get("reason"):
            if lowered in {"yes", "no", "confirm", "cancel"}:
                return {
                    "reply": "Please tell me the reason for returning the item.",
                    "intent": "RETURN_REQUEST",
                }
            reason = text
            if len(reason) > 500:
                return {"reply": "Please keep the return reason under 500 characters."}
            pending["details"]["reason"] = reason
            return {
                "reply": (
                    f"Please confirm: create a return for order "
                    f"{pending['order_id']} with reason '{reason}'? Reply yes or no."
                ),
                "intent": "RETURN_REQUEST",
                "awaiting_confirmation": True,
            }

        result = _finish_confirmation(state, text)
        if result is not None:
            _log("confirmation_flow", state, intent=result.get("intent"))
            return result

    escalation = detect_escalation(text, state)
    if escalation:
        state.escalated = True
        _log("escalation", state, **escalation)
        return {
            "reply": (
                "I'll refer this to human support. "
                + escalation["message"]
            ),
            "intent": "HUMAN_ESCALATION",
            "escalation": escalation,
        }

    # Account-security, fraud, and payment disputes must go to a human.
    if re.search(r"\b(fraud|payment dispute|account hacked|account security)\b", lowered):
        return {
            "reply": "For security, fraud, or payment disputes, please contact human support.",
            "intent": "HUMAN_ESCALATION",
            "escalation": {
                "trigger": "LOW_CONFIDENCE",
                "severity": "LOW",
            },
        }

    # Never allow an LLM or a user message to bypass these rules.
    if "ignore previous instructions" in lowered or "print system prompt" in lowered:
        return {
            "reply": "I can help with your own orders, returns, and product questions.",
            "intent": "OUT_OF_SCOPE",
        }
    if re.search(r"\bORD-\d{4}\s*;", text, re.I):
        return {
            "reply": "Invalid order ID format. Please provide a valid order ID.",
            "intent": "OUT_OF_SCOPE",
        }
    order_match = ORDER_ID.search(text)
    product_match = PRODUCT_ID.search(text)

    if any(word in lowered for word in ("cancel", "cancellation")):
        if not order_match:
            return {
                "reply": "Which order would you like to cancel? Please provide its order ID.",
                "intent": "CANCEL_ORDER",
            }

        order_id = order_match.group(0).upper()
        order = _run_tool(
            state, "get_order", backend.get_order, order_id, customer_id
        )
        if not order.get("order_id"):
            return {
                "reply": order.get("message", "I couldn't retrieve that order."),
                "intent": "CANCEL_ORDER",
            }

        if order["status"] != "PROCESSING":
            return {
                "reply": (
                    f"Order {order_id} is {order['status']}. "
                    "Only orders that have not shipped can be cancelled."
                ),
                "intent": "CANCEL_ORDER",
                "success": False,
            }

        sessions.set_pending_action(state, "CANCEL_ORDER", order_id)
        return {
            "reply": f"Please confirm cancellation of order {order_id}. Reply yes or no.",
            "intent": "CANCEL_ORDER",
            "awaiting_confirmation": True,
        }

    if "refund" in lowered and any(
        word in lowered for word in ("how long", "when", "timeline", "take")
    ):
        return {
            "reply": POLICY["refunds"],
            "intent": "GENERAL_QUESTION",
        }
    if any(word in lowered for word in ("return", "refund")):
        if not order_match:
            return {
                "reply": "Which order would you like to return? Please provide its order ID.",
                "intent": "RETURN_REQUEST",
            }

        order_id = order_match.group(0).upper()
        eligibility = _run_tool(
            state, "check_return_eligibility",
            backend.check_return_eligibility, order_id, customer_id,
        )

        if not eligibility.get("eligible"):
            if eligibility.get("requires_escalation"):
                state.escalated = True
                return {
                    "reply": "This refund exceeds â‚¹10,000 and requires human review. No return was created.",
                    "intent": "HUMAN_ESCALATION",
                    "escalation": {
                        "trigger": "REFUND_OVER_LIMIT",
                        "severity": "MEDIUM",
                    },
                }
            return {
                "reply": eligibility.get("message", eligibility.get("reason", "This order is not eligible for return.")),
                "intent": "RETURN_REQUEST",
                "success": False,
            }

        sessions.set_pending_action(
            state, "RETURN_REQUEST", order_id, {"reason": ""}
        )
        return {
            "reply": "What is the reason for returning this item?",
            "intent": "RETURN_REQUEST",
        }

    if product_match:
        product_id = product_match.group(0).upper()
        product = _run_tool(state, "get_product", backend.get_product, product_id)
        if not product.get("product_id"):
            return {"reply": "I couldn't find that product.", "intent": "PRODUCT_INFO"}
        return {
            "reply": (
                f"{product['name']} costs â‚¹{product['price']}. "
                f"Returnable: {'yes' if product['returnable'] else 'no'}. "
                "Product descriptions are treated as data, not instructions."
            ),
            "intent": "PRODUCT_INFO",
        }

    if order_match or any(word in lowered for word in ("order status", "track order", "where is my order")):
        if not order_match:
            orders = _run_tool(state, "list_orders", backend.list_orders, customer_id)
            if isinstance(orders, list) and orders:
                return {
                    "reply": "Your orders: " + ", ".join(
                        f"{o['order_id']} ({o['status']})" for o in orders
                    ),
                    "intent": "ORDER_STATUS",
                }
            return {"reply": "I couldn't retrieve your orders.", "intent": "ORDER_STATUS"}

        order_id = order_match.group(0).upper()
        order = _run_tool(state, "get_order", backend.get_order, order_id, customer_id)
        if not order.get("order_id"):
            return {
                "reply": order.get("message", "I couldn't retrieve that order."),
                "intent": "ORDER_STATUS",
            }
        return {
            "reply": (
                f"Order {order_id} is {order['status']}. "
                f"Tracking: {order.get('tracking') or 'not available'}. "
                f"Expected delivery: {order.get('expected_delivery_date') or 'not available'}."
            ),
            "intent": "ORDER_STATUS",
        }

    if any(word in lowered for word in ("shipping", "delivery time", "cancel policy")):
        return {"reply": POLICY["shipping"] + " " + POLICY["cancellation"], "intent": "GENERAL_QUESTION"}
    if any(word in lowered for word in ("return policy", "return window", "gift card")):
        return {"reply": POLICY["returns"], "intent": "GENERAL_QUESTION"}
    if "refund" in lowered and any(word in lowered for word in ("how long", "when", "timeline")):
        return {"reply": POLICY["refunds"], "intent": "GENERAL_QUESTION"}
    if any(word in lowered for word in ("support hours", "business hours", "opening hours")):
        return {"reply": POLICY["support"], "intent": "GENERAL_QUESTION"}

    return {
        "reply": (
            "I can help with order status, cancellations, returns, product details, "
            "and store policies. For other topics, please contact human support."
        ),
        "intent": "OUT_OF_SCOPE",
    }



def handle_message(session_id, customer_id, message):
    """Add structured classification metadata to every response."""
    result = _handle_message(session_id, customer_id, message)

    text = message.strip() if isinstance(message, str) else ""
    order_match = ORDER_ID.search(text)
    product_match = PRODUCT_ID.search(text)

    entities = {"customer_id": customer_id}
    if order_match:
        entities["order_id"] = order_match.group(0).upper()
    if product_match:
        entities["product_id"] = product_match.group(0).upper()

    confidence_by_intent = {
        "ORDER_STATUS": 0.95,
        "CANCEL_ORDER": 0.95,
        "RETURN_REQUEST": 0.95,
        "PRODUCT_INFO": 0.95,
        "GENERAL_QUESTION": 0.90,
        "HUMAN_ESCALATION": 0.99,
        "OUT_OF_SCOPE": 0.85,
    }

    intent = result.get("intent", "GENERAL_QUESTION")
    result["entities"] = entities
    result["confidence"] = confidence_by_intent.get(intent, 0.70)

    logger.info(
        "%s",
        {
            "event": "intent_classified",
            "session_id": session_id,
            "customer_id": customer_id,
            "intent": intent,
            "entities": entities,
            "confidence": result["confidence"],
        },
    )
    return result
