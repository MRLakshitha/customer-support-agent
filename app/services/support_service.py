from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Customer, Conversation, FAQ, Order


def get_customer_orders(db: Session, customer_id: str):
    customer = db.scalar(
        select(Customer).where(Customer.customer_id == customer_id)
    )

    if customer is None:
        return None

    orders = db.scalars(
        select(Order)
        .where(Order.customer_id == customer_id)
        .order_by(Order.order_date.desc())
    ).all()

    return {
        "customer_id": customer.customer_id,
        "customer_name": customer.name,
        "orders": [
            {
                "order_id": order.order_id,
                "product": order.product,
                "status": order.status,
                "order_date": order.order_date,
                "expected_delivery": order.expected_delivery,
            }
            for order in orders
        ],
    }


def get_order(
    db: Session,
    order_id: str,
    customer_id: str | None = None,
):
    conditions = [Order.order_id == order_id]

    if customer_id is not None:
        conditions.append(Order.customer_id == customer_id)

    order = db.scalar(
        select(Order).where(*conditions)
    )

    if order is None:
        return None

    return {
        "order_id": order.order_id,
        "customer_id": order.customer_id,
        "product": order.product,
        "status": order.status,
        "order_date": order.order_date,
        "expected_delivery": order.expected_delivery,
    }


def search_faqs(db: Session, question: str, limit: int = 5):
    terms = [
        term.strip(".,?!:;").lower()
        for term in question.split()
        if len(term.strip(".,?!:;")) > 2
    ]

    if not terms:
        return []

    conditions = [
        or_(
            FAQ.question.ilike(f"%{term}%"),
            FAQ.answer.ilike(f"%{term}%"),
            FAQ.category.ilike(f"%{term}%"),
        )
        for term in terms
    ]

    faqs = db.scalars(
        select(FAQ).where(or_(*conditions)).limit(limit)
    ).all()

    return [
        {
            "category": faq.category,
            "question": faq.question,
            "answer": faq.answer,
        }
        for faq in faqs
    ]


def save_conversation(
    db: Session,
    customer_id: str,
    question: str,
    answer: str,
):
    conversation = Conversation(
        customer_id=customer_id,
        question=question,
        answer=answer,
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return {
        "id": conversation.id,
        "customer_id": conversation.customer_id,
        "question": conversation.question,
        "answer": conversation.answer,
        "created_at": conversation.created_at.isoformat(),
    }


def get_conversation_history(
    db: Session,
    customer_id: str,
    limit: int = 20,
):
    records = db.scalars(
        select(Conversation)
        .where(Conversation.customer_id == customer_id)
        .order_by(Conversation.id.desc())
        .limit(limit)
    ).all()

    return [
        {
            "id": record.id,
            "question": record.question,
            "answer": record.answer,
            "created_at": record.created_at.isoformat(),
        }
        for record in reversed(records)
    ]