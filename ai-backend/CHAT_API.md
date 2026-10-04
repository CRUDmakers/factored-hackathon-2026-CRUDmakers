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
  files: ChatFile[];                   // spreadsheets generated this turn (often empty)
  trace_id: string;
};

type ChatFile = {
  file_id: string;
  filename: string;                    // e.g. "movimientos_junio.xlsx"
  format: "xlsx" | "csv" | "pdf";
  media_type: string;
  size_bytes: number;
  rows: number;                        // data rows, all sheets
  download_url: string;                // "/v1/files/{file_id}", relative to the AI backend
  expires_at: string;                  // ISO time; after it, the download answers 404
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

## Files (Excel / CSV)

When the customer asks for a spreadsheet ("mándame un Excel con mis movimientos de junio"), the agent reads the data with its tools and calls `generate_files` with a JSON payload. The backend builds the files (`src/ai_backend/files/`), stores them and returns them in `ChatResponse.files`. One call can produce several files.

Show one download button per file. The download needs the bearer token, so fetch it and save the blob (`downloadChatFile` in `frontend/src/api.ts`); a plain `<a href>` won't work.

```
GET /v1/files/{file_id}            Authorization: Bearer <access_token>
→ 200, the file, Content-Disposition: attachment; filename="…"; filename*=UTF-8''…
→ 401 login_required · 404 file_not_found (unknown, another customer's, or expired)
```

Files belong to the session's customer and expire after `FILE_TTL_HOURS` (default 24); expired rows are deleted at startup.

### The payload

The same JSON is the `generate_files` tool's arguments and the body of `POST /v1/files` (which also takes an optional `conversation_id` the customer owns, and answers `201 {files: ChatFile[]}`).

```json
{
  "files": [
    {
      "filename": "movimientos_junio",
      "format": "xlsx",
      "sheets": [
        {
          "name": "Movimientos",
          "columns": [
            {"header": "Fecha", "type": "date"},
            {"header": "Comercio", "type": "text"},
            {"header": "Monto", "type": "money"},
            {"header": "Moneda", "type": "text"}
          ],
          "rows": [["2026-06-15", "Uber", 12.5, "USD"]]
        }
      ]
    },
    {
      "filename": "resumen",
      "format": "csv",
      "sheets": [{"name": "Resumen", "columns": [{"header": "Total", "type": "money"}], "rows": [[12.5]]}]
    }
  ]
}
```

| Rule | |
|---|---|
| `files` | 1–5 files |
| `format` | `xlsx` (1–10 sheets) or `csv` (exactly 1 sheet) |
| `columns[].type` | `text` (default), `number`, `money` (2 decimals) or `date` (`YYYY-MM-DD` or ISO date-time) |
| `rows` | ≤ 2000 per sheet, one value per column (`null` = empty). A value that doesn't fit its type is kept as written |
| Names | `filename` is sanitised and gets the extension; sheet names ≤ 31 characters, unique, without `[ ] : * ? / \` |

xlsx files get a styled, frozen header row, a filter and column widths. csv files are UTF-8 with BOM (Excel shows accents) and comma-separated. Text that a spreadsheet would run as a formula (`=`, `+`, `-`, `@`) is always written as text.

## PDF reports

PDFs are not free-form: there is a fixed set of templates (`src/ai_backend/reports/`). When the customer asks for one ("quero o extrato de junho em PDF", "mándame el comprobante de esa transferencia"), the agent calls `generate_report` with only the report's name and parameters. The backend reads the data from the bank with the customer's session, lays it out in the conversation's language (es/pt) and returns the file in `ChatResponse.files`, like a spreadsheet (`format: "pdf"`, `media_type: "application/pdf"`; `rows` is the number of records listed). The download is the same `GET /v1/files/{file_id}`.

| `report` | Parameters | Content |
|---|---|---|
| `account_statement` | `date_from`, `date_to`, `product_id` (all optional) | Transactions of the period, oldest first; inflows/outflows/net per currency (approved only). Default: the last 30 days. At most 500 transactions (the newest; the PDF says so). |
| `balances` | none | Accounts, credit cards and loans with their balances today, and totals per currency. |
| `spending` | `date_from`, `date_to`, `months` (1–12), `product_id` | Spending in USD: total, monthly average, bars and table by category, by month (with change), by card or account. Default: the last 3 calendar months. |
| `recurring_payments` | none | Recurring payments expected this month: paid, scheduled or due (overdue marked), with the total still due. |
| `transaction_receipt` | `transaction_id` (required) | Receipt of one transaction: amount, status (and decline reason), date, channel, product, counterparty, place. Refused (`under_review`) for a transaction flagged as fraud. |

Card and account numbers show only their last 4 digits; internal IDs (`PRD-…`) never appear. The footer has the customer ID, the issue time and "page X of Y".

The app can request the same PDFs directly, without the chat:

```
GET  /v1/reports                    → {reports: [{report, title: {es, pt}, description, parameters, endpoint}]}
POST /v1/reports/{report}           Authorization: Bearer <access_token>
     {"language": "pt", "date_from": "2026-06-01", "date_to": "2026-06-30", "product_id": "PRD-…",
      "transaction_id": "TRX-…", "conversation_id": "conv_…"}      (all optional; each report uses its own)
→ 201 {files: [ChatFile]}
→ 401 login_required · 404 not_found (product/transaction, or another customer's) · 404 conversation_not_found
→ 422 invalid_arguments · 422 under_review · 503 bank_unavailable
```

## Other endpoints

| Method | Path | Returns |
|---|---|---|
| `GET` | `/v1/conversations/{conversation_id}/trace` | Every step of the conversation (nodes, tools, policy decisions, tokens, timings), for the human-agent panel and the demo. Only the conversation's customer. |
| `GET` | `/v1/handoffs/{handoff_id}` | The handoff record: reason codes, priority, verified facts, actions taken, evidence, the model's summary and open questions (ARCHITECTURE §10). Only the handoff's customer, until agent roles exist. |
| `POST` | `/v1/files` | Builds files from the payload above, for the session's customer. |
| `GET` | `/v1/files/{file_id}` | A generated file or PDF report (see above). |
| `GET` | `/v1/reports` | The PDF report catalogue (see above). |
| `POST` | `/v1/reports/{report}` | Builds one PDF report from the bank's data, for the session's customer. |
| `GET` | `/v1/health` | `{status: "ok" \| "degraded", checks: {models, bank, storage}}`; 503 when degraded. |
