import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Customer, Order, FAQ


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSessionLocal = sessionmaker(
    bind=test_engine,
    autoflush=False,
    expire_on_commit=False,
)

CUSTOMER_TOKEN = "test-token-customer-001"
OTHER_CUSTOMER_TOKEN = "test-token-customer-002"

CUSTOMER_HEADERS = {
    "Authorization": f"Bearer {CUSTOMER_TOKEN}",
}

OTHER_CUSTOMER_HEADERS = {
    "Authorization": f"Bearer {OTHER_CUSTOMER_TOKEN}",
}


@pytest.fixture
def client(monkeypatch):
    # Test-only tokens. Never use these tokens outside tests.
    monkeypatch.setenv(
        "CUSTOMER_API_TOKENS",
        json.dumps({
            "CUST001": CUSTOMER_TOKEN,
            "CUST002": OTHER_CUSTOMER_TOKEN,
            "CUST-001": "test-token-agent-001",
        }),
    )

    Base.metadata.create_all(bind=test_engine)

    db = TestSessionLocal()
    try:
        db.add_all([
            Customer(
                customer_id="CUST001",
                name="Alex Johnson",
                email="alex@example.com",
            ),
            Customer(
                customer_id="CUST002",
                name="Jordan Smith",
                email="jordan@example.com",
            ),
            Order(
                order_id="ORD1001",
                customer_id="CUST001",
                product="Wireless Headphones",
                status="Shipped",
                order_date="2026-10-05",
                expected_delivery="2026-10-12",
            ),
            Order(
                order_id="ORD2001",
                customer_id="CUST002",
                product="Laptop Stand",
                status="Processing",
                order_date="2026-10-06",
                expected_delivery="2026-10-14",
            ),
            FAQ(
                category="shipping",
                question="Where is my order?",
                answer="Check the order status for delivery updates.",
            ),
        ])
        db.commit()
    finally:
        db.close()

    def override_get_db():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)


# --------------------------------------------------
# Public endpoints
# --------------------------------------------------

def test_home_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_search_faqs(client):
    response = client.get(
        "/faqs",
        params={"q": "shipping"},
    )
    assert response.status_code == 200
    assert response.json()["count"] >= 1


# --------------------------------------------------
# Authentication tests
# --------------------------------------------------

def test_order_requires_authentication(client):
    response = client.get("/orders/ORD1001")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_token_is_rejected(client):
    response = client.get(
        "/orders/ORD1001",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401


# --------------------------------------------------
# Order endpoint tests
# --------------------------------------------------

def test_get_order(client):
    response = client.get(
        "/orders/ORD1001",
        headers=CUSTOMER_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "Shipped"
    assert response.json()["customer_id"] == "CUST001"


def test_order_not_found(client):
    response = client.get(
        "/orders/UNKNOWN",
        headers=CUSTOMER_HEADERS,
    )
    assert response.status_code == 404


def test_customer_cannot_access_another_customers_order(client):
    response = client.get(
        "/orders/ORD2001",
        headers=CUSTOMER_HEADERS,
    )

    # The API does not disclose whether another customer's order exists.
    assert response.status_code == 404


# --------------------------------------------------
# Customer order tests
# --------------------------------------------------

def test_get_customer_orders(client):
    response = client.get(
        "/customers/CUST001/orders",
        headers=CUSTOMER_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["customer_id"] == "CUST001"
    assert len(response.json()["orders"]) == 1


def test_customer_not_found(client):
    response = client.get(
        "/customers/UNKNOWN/orders",
        headers=CUSTOMER_HEADERS,
    )

    # A customer cannot query another ID, even if it does not exist.
    assert response.status_code == 403


def test_customer_cannot_access_another_customers_orders(client):
    response = client.get(
        "/customers/CUST002/orders",
        headers=CUSTOMER_HEADERS,
    )
    assert response.status_code == 403


def test_second_customer_can_access_own_orders(client):
    response = client.get(
        "/customers/CUST002/orders",
        headers=OTHER_CUSTOMER_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["customer_id"] == "CUST002"
    assert len(response.json()["orders"]) == 1


# --------------------------------------------------
# Conversation history tests
# --------------------------------------------------

def test_customer_history(client):
    response = client.get(
        "/customers/CUST001/history",
        headers=CUSTOMER_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["customer_id"] == "CUST001"
    assert response.json()["history"] == []


def test_customer_cannot_access_another_customers_history(client):
    response = client.get(
        "/customers/CUST002/history",
        headers=CUSTOMER_HEADERS,
    )
    assert response.status_code == 403


# --------------------------------------------------
# Chat identity tests
# --------------------------------------------------

def test_chat_rejects_another_customers_identity(client):
    response = client.post(
        "/chat",
        headers=CUSTOMER_HEADERS,
        json={
            "customer_id": "CUST002",
            "message": "Show me my orders",
        },
    )
    assert response.status_code == 403


def test_agent_chat_rejects_another_customers_identity(client):
    response = client.post(
        "/agent/chat",
        headers={"Authorization": "Bearer test-token-agent-001"},
        json={
            "session_id": "test-session",
            "customer_id": "CUST-002",
            "message": "Show my orders",
        },
    )
    assert response.status_code == 403