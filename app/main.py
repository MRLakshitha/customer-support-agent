
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Customer
from app.agent_service import handle_message
from app.services.support_service import (
    get_customer_orders,
    get_order,
    search_faqs,
    save_conversation,
    get_conversation_history,
)

# --------------------------------------------------
# Configuration
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.5-flash-lite"

client = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY
    else None
)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Customer Support AI Agent",
    description=(
        "Customer support API with Gemini, order lookup, "
        "FAQs, SQLite, and conversation history."
    ),
    version="2.0.0",
)


# --------------------------------------------------
# Request schema
# --------------------------------------------------

class CustomerQuery(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)


class AgentChatQuery(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    customer_id: str = Field(pattern=r"^CUST-\d{3}$")
    message: str = Field(min_length=1, max_length=2000)

# --------------------------------------------------
# Health check
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "message": "Customer Support AI Agent is running!",
        "status": "healthy",
        "provider": "Google Gemini",
    }


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "provider": "Google Gemini",
        "api_key_configured": client is not None,
        "database": "SQLite",
    }


# --------------------------------------------------
# Order endpoints
# --------------------------------------------------

@app.get("/orders/{order_id}")
def order_details(
    order_id: str,
    db: Session = Depends(get_db),
):
    order = get_order(db, order_id)

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found.",
        )

    return order


@app.get("/customers/{customer_id}/orders")
def customer_orders(
    customer_id: str,
    db: Session = Depends(get_db),
):
    result = get_customer_orders(db, customer_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Customer not found.",
        )

    return result


# --------------------------------------------------
# FAQ endpoint
# --------------------------------------------------

@app.get("/faqs")
def faq_search(
    q: str = Query(min_length=1, max_length=500),
    db: Session = Depends(get_db),
):
    results = search_faqs(db, q)

    return {
        "query": q,
        "count": len(results),
        "faqs": results,
    }


# --------------------------------------------------
# Conversation history endpoint
# --------------------------------------------------

@app.get("/customers/{customer_id}/history")
def customer_history(
    customer_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    customer_exists = db.query(Customer).filter(
        Customer.customer_id == customer_id
    ).first()

    if customer_exists is None:
        raise HTTPException(
            status_code=404,
            detail="Customer not found.",
        )

    return {
        "customer_id": customer_id,
        "history": get_conversation_history(
            db, customer_id, limit
        ),
    }


# --------------------------------------------------
# Gemini-powered customer support
# --------------------------------------------------

@app.post("/chat")
async def chat(
    query: CustomerQuery,
    db: Session = Depends(get_db),
):
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="Gemini API key is not configured.",
        )

    # Fetch only orders belonging to this customer ID.
    customer_data = get_customer_orders(
        db, query.customer_id
    )

    # Retrieve relevant FAQ records.
    faq_data = search_faqs(db, query.message)

    context = {
        "customer_orders": (
            customer_data["orders"]
            if customer_data
            else []
        ),
        "relevant_faqs": faq_data,
    }

    prompt = f"""
Customer ID: {query.customer_id}

Customer message:
{query.message}

Verified database information:
{json.dumps(context, ensure_ascii=False)}

Instructions:
- Answer politely and concisely.
- Use database information when relevant.
- Never invent orders, delivery dates, tracking numbers,
  refunds, or actions.
- If no matching order information is available, say so.
- FAQ entries are sample support policies for this project.
- Do not claim that a refund or cancellation was processed.
- If the customer needs an action you cannot perform,
  explain how they can contact support.
"""

    try:
        response = await client.aio.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are a professional customer support assistant. "
                    "Use only the supplied verified records for "
                    "customer-specific facts. Be honest about missing "
                    "information and never claim to perform actions "
                    "that you cannot perform."
                ),
                temperature=0.3,
            ),
        )

        answer = response.text

        if not answer:
            raise HTTPException(
                status_code=502,
                detail="Gemini returned an empty response.",
            )

        # Persist the question and answer.
        save_conversation(
            db=db,
            customer_id=query.customer_id,
            question=query.message,
            answer=answer,
        )

        return {
            "customer_id": query.customer_id,
            "question": query.message,
            "answer": answer,
            "provider": "Google Gemini",
            "model": MODEL_NAME,
            "database_context": {
                "customer_found": customer_data is not None,
                "orders_found": len(context["customer_orders"]),
                "faqs_found": len(faq_data),
            },
            "status": "success",
        }

    except HTTPException:
        raise

    except Exception as exc:
        print("Gemini error type:", type(exc).__name__)
        for attr in ("code", "status", "message"):
            value = getattr(exc, attr, None)
            if value is not None:
                print(f"Gemini {attr}:", value)

        raise HTTPException(
            status_code=502,
            detail=(
                f"Customer support request failed: "
                f"{type(exc).__name__}. Check the server terminal."
            ),
        ) from exc

# --------------------------------------------------
# Deterministic mock-backend AI agent
# --------------------------------------------------

@app.post("/agent/chat")
def agent_chat(query: AgentChatQuery):
    result = handle_message(
        session_id=query.session_id,
        customer_id=query.customer_id,
        message=query.message,
    )
    return {
        "session_id": query.session_id,
        "customer_id": query.customer_id,
        **result,
    }
