# Customer Support AI Agent

A Python-based e-commerce customer support agent built with FastAPI, deterministic workflows, and a mock e-commerce backend. This project demonstrates order support, cancellation and return workflows, policy enforcement, session isolation, security checks, and human escalation.

## Features

* Order status and tracking inquiries
* Order cancellation with explicit customer confirmation
* Return eligibility, reason collection, and confirmation
* Refund-limit enforcement and human escalation
* Customer ownership checks and session isolation
* Prompt-injection and malformed-ID handling
* Intent, entity, and confidence metadata
* Retry handling for backend tool failures
* REST API endpoints using FastAPI
* Automated tests and deterministic evaluation
* Live Gemini response evaluation

## Technology Stack

* Python 3.12
* FastAPI and Pydantic
* SQLAlchemy and SQLite
* Google GenAI SDK for Gemini integration
* pytest for automated testing
* Git and GitHub for version control

## Project Structure

```text
customer-support-agent/
├── app/
│   ├── agent_service.py
│   ├── agent_state.py
│   ├── database.py
│   ├── main.py
│   ├── mock_backend.py
│   ├── models.py
│   ├── seed.py
│   └── services/
│       └── support_service.py
├── tests/
│   ├── test_agent.py
│   └── test_api.py
├── eval/
│   ├── run_eval.py
│   ├── eval_results.json
│   ├── run_gemini_eval.py
│   └── gemini_eval_results.json
├── transcripts/
│   └── sample_transcripts.md
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Setup and Installation

### 1. Clone the repository

```powershell
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd customer-support-agent
```

If you already have the project locally, open PowerShell in your project directory instead.

### 2. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 4. Configure environment variables

Create your local environment file:

```powershell
Copy-Item .env.example .env
```

Open `.env` and add your Gemini API key if you intend to use Gemini-powered features.

Example:

```text
GEMINI_API_KEY=your_api_key_here
MOCK_CURRENT_DATE=
```

Replace the placeholder with your own valid key. Never commit `.env` or expose API credentials. Keep `.env.example` free of real secrets.

## Run the Application

Start the FastAPI development server:

```powershell
python -m uvicorn app.main:app --reload
```

Open the interactive API documentation:

http://127.0.0.1:8000/docs

## API Endpoints

| Method | Endpoint                          | Purpose                               |
| ------ | --------------------------------- | ------------------------------------- |
| GET    | `/health`                         | Health check                          |
| GET    | `/orders/{order_id}`              | Retrieve an order                     |
| GET    | `/customers/{customer_id}/orders` | List a customer's orders              |
| GET    | `/faqs`                           | Retrieve FAQ data                     |
| POST   | `/agent/chat`                     | Interact with the support agent       |
| POST   | `/chat`                           | Existing Gemini-powered chat endpoint |

### Example Request

Send a `POST` request to `/agent/chat` using the following JSON body:

```json
{
  "session_id": "demo-session-001",
  "customer_id": "CUST-001",
  "message": "Where is order ORD-1001?"
}
```

Use `/docs` to view the available endpoints and request schemas.

## Agent Workflows and Safety

* Cancellation requires explicit confirmation and backend validation.
* Returns require an order, a reason, eligibility checks, and confirmation.
* Refund requests exceeding INR 10,000 require human review.
* Ownership checks prevent access to another customer's orders.
* Malformed order IDs are rejected.
* Product descriptions are treated as untrusted data rather than instructions.
* Repeated tool failures can trigger escalation.

## Testing

Run the automated test suite:

```powershell
python -m pytest -v
```

Run the deterministic evaluation:

```powershell
python -m eval.run_eval
```

Run the live Gemini evaluation:

```powershell
python -m eval.run_gemini_eval
```

The Gemini evaluation requires a valid `GEMINI_API_KEY` in your local `.env` file.

Evaluation reports are stored in the `eval/` directory.

## Sample Transcripts

See `transcripts/sample_transcripts.md` for illustrative order-status, cancellation, return, escalation, and prompt-injection scenarios.

These transcripts are examples and should not be presented as production customer conversations.

## Limitations

* The agent workflow uses deterministic rules and an in-memory mock backend.
* Mock data and in-memory state are not suitable for production order processing.
* Confidence values are rule-based and are not calibrated probabilities.
* Deterministic evaluation does not measure overall live LLM performance.
* Gemini evaluation uses phrase matching rather than comprehensive semantic or security assessment.
* Additional testing is needed for timeouts, escalation coverage, logging, and edge cases.

## Security Considerations

* Never commit `.env` or expose API credentials.
* Use synthetic customer data in demonstrations.
* Validate high-impact actions in backend code, not only through model instructions.
* Treat customer messages and product descriptions as untrusted input.
* Do not connect the mock backend to real customer operations without appropriate authentication, authorization, monitoring, and production-grade safeguards.

## Future Improvements

* Add semantic evaluation and broader adversarial test cases.
* Expand structured logging and observability.
* Improve timeout and retry tests.
* Replace mock data with authenticated production services when appropriate.
* Add CI checks to run automated tests on changes.
