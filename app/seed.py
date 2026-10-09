
from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Customer, Order, FAQ

# Create tables if they do not exist.
Base.metadata.create_all(bind=engine)

customers = [
    {
        "customer_id": "CUST001",
        "name": "Alex Johnson",
        "email": "alex@example.com",
    },
    {
        "customer_id": "CUST002",
        "name": "Priya Sharma",
        "email": "priya@example.com",
    },
]

orders = [
    {
        "order_id": "ORD1001",
        "customer_id": "CUST001",
        "product": "Wireless Headphones",
        "status": "Shipped",
        "order_date": "2026-10-05",
        "expected_delivery": "2026-10-12",
    },
    {
        "order_id": "ORD1002",
        "customer_id": "CUST001",
        "product": "Laptop Stand",
        "status": "Processing",
        "order_date": "2026-10-08",
        "expected_delivery": "2026-10-15",
    },
    {
        "order_id": "ORD2001",
        "customer_id": "CUST002",
        "product": "Bluetooth Speaker",
        "status": "Delivered",
        "order_date": "2026-10-01",
        "expected_delivery": "2026-10-06",
    },
]

faqs = [
    {
        "category": "shipping",
        "question": "How long does shipping take?",
        "answer": (
            "Standard shipping usually takes 5-7 business days. "
            "Actual delivery dates depend on the order and carrier."
        ),
    },
    {
        "category": "returns",
        "question": "What is the return policy?",
        "answer": (
            "Eligible unused products can be returned within 30 days "
            "of delivery, subject to the applicable product policy."
        ),
    },
    {
        "category": "refunds",
        "question": "How long do refunds take?",
        "answer": (
            "After a return is approved and processed, refunds generally "
            "take 5-10 business days to appear, depending on the payment "
            "provider."
        ),
    },
    {
        "category": "cancellations",
        "question": "Can I cancel an order?",
        "answer": (
            "Orders that have not shipped may be eligible for cancellation. "
            "Contact support to confirm eligibility."
        ),
    },
]


def seed_database():
    with SessionLocal() as db:
        for item in customers:
            existing = db.scalar(
                select(Customer).where(
                    Customer.customer_id == item["customer_id"]
                )
            )
            if existing is None:
                db.add(Customer(**item))

        for item in orders:
            existing = db.scalar(
                select(Order).where(Order.order_id == item["order_id"])
            )
            if existing is None:
                db.add(Order(**item))

        for item in faqs:
            existing = db.scalar(
                select(FAQ).where(FAQ.question == item["question"])
            )
            if existing is None:
                db.add(FAQ(**item))

        db.commit()

    print("Sample customers, orders, and FAQs are ready.")


if __name__ == "__main__":
    seed_database()