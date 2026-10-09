
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


@pytest.fixture
def client():
    Base.metadata.create_all(bind=test_engine)

    db = TestSessionLocal()
    db.add_all([
        Customer(
            customer_id="CUST001",
            name="Alex Johnson",
            email="alex@example.com",
        ),
        Order(
            order_id="ORD1001",
            customer_id="CUST001",
            product="Wireless Headphones",
            status="Shipped",
            order_date="2026-10-05",
            expected_delivery="2026-10-12",
        ),
        FAQ(
            category="shipping",
            question="Where is my order?",
            answer="Check the order status for delivery updates.",
        ),
    ])
    db.commit()
    db.close()

    def override_get_db():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def test_home_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_get_order(client):
    response = client.get("/orders/ORD1001")
    assert response.status_code == 200
    assert response.json()["status"] == "Shipped"


def test_order_not_found(client):
    response = client.get("/orders/UNKNOWN")
    assert response.status_code == 404


def test_get_customer_orders(client):
    response = client.get("/customers/CUST001/orders")
    assert response.status_code == 200
    assert response.json()["customer_id"] == "CUST001"
    assert len(response.json()["orders"]) == 1


def test_customer_not_found(client):
    response = client.get("/customers/UNKNOWN/orders")
    assert response.status_code == 404


def test_search_faqs(client):
    response = client.get("/faqs", params={"q": "shipping"})
    assert response.status_code == 200
    assert response.json()["count"] >= 1


def test_customer_history(client):
    response = client.get("/customers/CUST001/history")
    assert response.status_code == 200
    assert response.json()["customer_id"] == "CUST001"
    assert response.json()["history"] == []