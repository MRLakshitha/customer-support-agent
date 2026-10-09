import json
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Security,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
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
        "FAQs, SQLite, authentication, and conversation history."
    ),
    version="2.1.0",
)

bearer_scheme = HTTPBearer(auto_error=False)


# --------------------------------------------------
# Request schemas
# --------------------------------------------------

class CustomerQuery(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)


class AgentChatQuery(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    customer_id: str = Field(pattern=r"^CUST-\d{3}$")
    message: str = Field(min_length=1, max_length=2000)


# --------------------------------------------------
# Authentication
# --------------------------------------------------

def get_authenticated_customer_id(
    credentials: HTTPAuthorizationCredentials | None = Security(
        bearer_scheme
    ),
) -> str:
    """
    Authenticate a customer using a Bearer token.

    CUSTOMER_API_TOKENS must contain a JSON object mapping
    customer IDs to secret tokens.

    Example:
    {"CUST001": "a-long-random-secret-token"}
    """
    configured_tokens = os.getenv("CUSTOMER_API_TOKENS")

    if not configured_tokens:
        raise HTTPException(
            status_code=503,
            detail="Customer authentication is not configured.",
        )

    try:
        token_map = json.loads(configured_tokens)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(
            status_code=503,
            detail="Customer authentication configuration is invalid.",
        )

    if not isinstance(token_map, dict) or not token_map:
        raise HTTPException(
            status_code=503,
            detail="Customer authentication configuration is invalid.",
        )

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    supplied_token = credentials.credentials

    if not supplied_token:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    for customer_id, expected_token in token_map.items():
        if (
            isinstance(customer_id, str)
            and isinstance(expected_token, str)
            and expected_token
            and secrets.compare_digest(
                supplied_token,
                expected_token,
            )
        ):
            return customer_id

    raise HTTPException(
        status_code=401,
        detail="Invalid authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_customer_access(
    requested_customer_id: str,
    authenticated_customer_id: str,
) -> None:
    """Prevent a customer from accessing another customer's data."""
    if not secrets.compare_digest(
        requested_customer_id,
        authenticated_customer_id,
    ):
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to access this customer's data.",
        )


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
    customer_id: str = Depends(get_authenticated_customer_id),
    db: Session = Depends(get_db),
):
    # Only return an order owned by the authenticated customer.
    order = get_order(
        db,
        order_id,
        customer_id=customer_id,
    )

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found.",
        )

    return order


@app.get("/customers/{customer_id}/orders")
def customer_orders(
    customer_id: str,
    authenticated_customer_id: str = Depends(
        get_authenticated_customer_id
    ),
    db: Session = Depends(get_db),
):
    require_customer_access(
        customer_id,
        authenticated_customer_id,
    )

    result = get_customer_orders(db, customer_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Customer not found.",
        )

    return result


# --------------------------------------------------
# FAQ endpoint (public)
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
    authenticated_customer_id: str = Depends(
        get_authenticated_customer_id
    ),
    db: Session = Depends(get_db),
):
    require_customer_access(
        customer_id,
        authenticated_customer_id,
    )

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
            db,
            customer_id,
            limit,
        ),
    }


# --------------------------------------------------
# Gemini-powered customer support
# --------------------------------------------------

@app.post("/chat")
async def chat(
    query: CustomerQuery,
    authenticated_customer_id: str = Depends(
        get_authenticated_customer_id
    ),
    db: Session = Depends(get_db),
):
    require_customer_access(
        query.customer_id,
        authenticated_customer_id,
    )

    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Gemini API key is not configured.",
        )

    customer_data = get_customer_orders(
        db,
        authenticated_customer_id,
    )

    if customer_data is None:
        raise HTTPException(
            status_code=404,
            detail="Customer not found.",
        )

    faq_data = search_faqs(db, query.message)

    context = {
        "customer_orders": customer_data["orders"],
        "relevant_faqs": faq_data,
    }

    prompt = f"""
Customer ID: {authenticated_customer_id}

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

        save_conversation(
            db=db,
            customer_id=authenticated_customer_id,
            question=query.message,
            answer=answer,
        )

        return {
            "customer_id": authenticated_customer_id,
            "question": query.message,
            "answer": answer,
            "provider": "Google Gemini",
            "model": MODEL_NAME,
            "database_context": {
                "customer_found": True,
                "orders_found": len(context["customer_orders"]),
                "faqs_found": len(faq_data),
            },
            "status": "success",
        }

    except HTTPException:
        raise

    except Exception as exc:
        print("Gemini error type:", type(exc).__name__)

        raise HTTPException(
            status_code=502,
            detail=(
                "Customer support request failed. "
                "Check the server terminal for details."
            ),
        ) from exc


# --------------------------------------------------
# Deterministic mock-backend AI agent
# --------------------------------------------------

@app.post("/agent/chat")
def agent_chat(
    query: AgentChatQuery,
    authenticated_customer_id: str = Depends(
        get_authenticated_customer_id
    ),
):
    require_customer_access(
        query.customer_id,
        authenticated_customer_id,
    )

    result = handle_message(
        session_id=query.session_id,
        customer_id=authenticated_customer_id,
        message=query.message,
    )

    return {
        "session_id": query.session_id,
        "customer_id": authenticated_customer_id,
        **result,
    }