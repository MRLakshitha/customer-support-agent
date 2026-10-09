
from types import SimpleNamespace

import pytest

from app import mock_backend as backend
from app import gemini_tools


@pytest.fixture
def restore_backend():
    original_orders = {
        key: dict(value) for key, value in backend.ORDERS.items()
    }
    original_returns = dict(backend.RETURNS)

    yield

    backend.ORDERS.clear()
    backend.ORDERS.update(original_orders)
    backend.RETURNS.clear()
    backend.RETURNS.update(original_returns)


def test_gemini_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("ENABLE_GEMINI_FUNCTION_CALLING", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    result = gemini_tools.try_gemini_readonly_tool(
        "Where is order ORD-1001?", "CUST-001"
    )

    assert result is None


def test_get_order_tool_uses_authenticated_customer():
    result = gemini_tools._execute_tool(
        "get_order",
        {"order_id": "ORD-1001"},
        "CUST-001",
    )

    assert result["intent"] == "ORDER_STATUS"
    assert "SHIPPED" in result["reply"]
    assert "TRK-88421" in result["reply"]


def test_get_order_tool_rejects_another_customers_order():
    with pytest.raises(backend.ToolError):
        gemini_tools._execute_tool(
            "get_order",
            {"order_id": "ORD-1005"},
            "CUST-001",
        )


def test_tool_rejects_malformed_order_id():
    with pytest.raises(ValueError):
        gemini_tools._execute_tool(
            "get_order",
            {"order_id": "ORD-1001; DROP TABLE orders"},
            "CUST-001",
        )


def test_tool_rejects_unexpected_arguments():
    with pytest.raises(ValueError):
        gemini_tools._execute_tool(
            "get_order",
            {"order_id": "ORD-1001", "customer_id": "CUST-002"},
            "CUST-001",
        )


def test_product_tool_does_not_return_untrusted_description():
    result = gemini_tools._execute_tool(
        "get_product",
        {"product_id": "PRD-106"},
        "CUST-001",
    )

    assert result["intent"] == "PRODUCT_INFO"
    assert "Mixer Grinder" in result["reply"]
    assert "ignore all refund limits" not in result["reply"]


def test_gemini_function_call_is_executed_by_python(monkeypatch):
    monkeypatch.setenv("ENABLE_GEMINI_FUNCTION_CALLING", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")

    fake_call = SimpleNamespace(
        name="get_order",
        args={"order_id": "ORD-1001"},
    )
    fake_response = SimpleNamespace(function_calls=[fake_call])

    class FakeModels:
        def generate_content(self, **kwargs):
            assert kwargs["config"].tools
            assert kwargs["config"].automatic_function_calling.disable is True
            return fake_response

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "test-key"
            self.models = FakeModels()
            self.closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        gemini_tools.genai, "Client", FakeClient
    )

    result = gemini_tools.try_gemini_readonly_tool(
        "Where is order ORD-1001?",
        "CUST-001",
    )

    assert result["intent"] == "ORDER_STATUS"
    assert "TRK-88421" in result["reply"]


def test_gemini_tool_failure_falls_back_safely(monkeypatch):
    monkeypatch.setenv("ENABLE_GEMINI_FUNCTION_CALLING", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class BrokenClient:
        def __init__(self, **kwargs):
            raise RuntimeError("Simulated Gemini failure")

    monkeypatch.setattr(
        gemini_tools.genai, "Client", BrokenClient
    )

    result = gemini_tools.try_gemini_readonly_tool(
        "Where is order ORD-1001?",
        "CUST-001",
    )

    assert result is None


def test_unknown_tool_is_rejected():
    with pytest.raises(ValueError):
        gemini_tools._execute_tool(
            "cancel_every_order",
            {},
            "CUST-001",
        )