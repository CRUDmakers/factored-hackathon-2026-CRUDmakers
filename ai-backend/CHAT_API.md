# Chat API: contract for the frontend

How the Assistant panel (`frontend/src/pages/Assistant.tsx`) talks to the AI backend. Implementation: `SPEC.md` §8.2 and §9. Base URL in Compose: `http://localhost:8000`.

## Authentication

Use the **same session token** the frontend already gets from Node (`POST /auth/test-sessions`):

```
Authorization: Bearer <access_token>
```

The AI backend checks the token with Node on every request, so an expired session or a logout in Node also ends the chat. It never needs the service key.

CORS allows the origins in `CORS_ORIGINS` (default `http://localhost:5173`), with the `Authorization` and `Content-Type` headers.

## `POST /v1/chat`

One request per customer message, or per click on a confirmation button.

```ts
type ChatRequest = {
  conversation_id?: string;            // omit on the first message; then send back the one you got
  message?: string;                    // 1–2000 characters
  confirmation?: { action_id: string; decision: "approve" | "reject" };
};                                     // send a message, a confirmation, or both

type ChatResponse = {
  conversation_id: string;
  turn_id: string;
  status: "answered" | "awaiting_confirmation" | "handed_off" | "refused";
  message: string;                     // always show this, as the assistant's bubble
  language: "es" | "pt";               // the language the customer is writing in
  pending_action: PendingAction | null;
  handoff: { handoff_id: string } | null;
  trace_id: string;
};

type PendingAction = {
  action_id: string;                   // send it back in `confirmation`
  summary: string;                     // same text as `message`; built by code from the bank's preview
  preview: PaymentPreview;             // Node's dry-run result, if you want to render your own card
  expires_at: string;                  // ISO time; after it, approving does nothing
};
```

`preview` has the same shape as Node's `?dry_run=true` response for `/transfers` and `/bill-payments`. The fields the Pay screen already uses are all there: `amount`, `currency`, `source.debited_amount`, `source.balance_after`, `exchange`, `counterparty.recipient_name`, `counterparty.destination_amount`.

### What to do with each status

| `status` | Show | Then |
|---|---|---|
| `answered` | `message` | Wait for the next message. |
| `awaiting_confirmation` | `message` (it ends with "¿Confirmas?" / "Confirma?") plus two buttons, **Confirm** and **Cancel** | Button → `POST /v1/chat` with `{conversation_id, confirmation: {action_id, decision}}`. Typing "sí/sim" or "no/não" also works. Any other message cancels the payment. |
| `handed_off` | `message`; it includes the reference `HND-…` | Optional: show a "sent to an agent" state. The record is at `GET /v1/handoffs/{handoff_id}`. |
| `refused` | `message` (e.g. "only Spanish or Portuguese") | Nothing else. |

A payment is **never** executed without the confirmation, and never more than once, even if the button is clicked twice.

### Errors

| HTTP | Body | Meaning |
|---|---|---|
| 401 | `{"status": "login_required", "message": "…"}` | Session missing, expired or ended. Handle it like Node's 401: back to login. |
| 404 | `{"error": "conversation_not_found", …}` | Unknown `conversation_id`, or another customer's. Start a new conversation. |
| 422 | FastAPI validation error | The request is malformed (e.g. neither `message` nor `confirmation`). |
| 503 | `{"error": "model_unavailable" \| "bank_unavailable", …}` | The assistant can't work right now. Show a retry message. |

### Example

```ts
const AI_URL = import.meta.env.VITE_AI_URL ?? "http://localhost:8000";

async function sendChat(token: string, body: ChatRequest): Promise<ChatResponse> {
  const res = await fetch(`${AI_URL}/v1/chat`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 401) throw new SessionLost();       // same handling as api.ts
  if (!res.ok) throw new Error((await res.json()).message);
  return res.json();
}

// First message
let r = await sendChat(token, { message: "Quiero pagar 100 dólares de mi tarjeta" });
// r.status === "awaiting_confirmation" → render r.message + [Confirm] [Cancel]
r = await sendChat(token, {
  conversation_id: r.conversation_id,
  confirmation: { action_id: r.pending_action!.action_id, decision: "approve" },
});
// r.status === "answered", r.message === "Listo: la operación fue aprobada. … Comprobante: TRX-…"
```

In Docker, pass the URL at build time like `VITE_API_URL`: add `ARG VITE_AI_URL` to `frontend/Dockerfile`, and `VITE_AI_URL: ${FRONTEND_AI_URL:-http://localhost:8000}` to the frontend's build args in `docker-compose.yml`.

## Other endpoints

| Method | Path | Returns |
|---|---|---|
| `GET` | `/v1/conversations/{conversation_id}/trace` | Every step of the conversation (nodes, tools, policy decisions, tokens, timings), for the human-agent panel and the demo. Only the conversation's customer. |
| `GET` | `/v1/handoffs/{handoff_id}` | The handoff record: reason codes, priority, verified facts, actions taken, evidence, the model's summary and open questions (ARCHITECTURE §10). Only the handoff's customer, until agent roles exist. |
| `GET` | `/v1/health` | `{status: "ok" \| "degraded", checks: {models, bank, storage}}`; 503 when degraded. |
