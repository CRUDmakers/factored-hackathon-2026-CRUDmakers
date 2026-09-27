# Transaccional Workflow: What the Data Supports

This is based on six months of data (H1 2025: 722,568 transactions, 129,613 customers, 39,569 "Transaccional" contacts). It lists what works well, what works with caveats, and what the data can't support.

## What the data gives you

- **Transaction types:** Purchase 25%, Withdrawal 22%, Transfer 20%, Payment 17%, Deposit 14%, Adjustment 3%.
- **Channels:** POS, ATM, Web, App, Branch, Transfer.
- **Status:** 92% Approved, 5% Declined, 2% Pending, 1% Reversed.
- **Transactions follow the product logically:** cards have purchases, accounts have deposits, transfers and withdrawals, and loans have payments and adjustments. The agent can explain *why* a transaction appears on a given product.
- **Currencies:**
    - USD 55%, COP 27%, ARS 18%.
    - `amount_usd` is filled for 95% of COP and ARS amounts.
    - The exchange-rate table has daily buy and sell rates for **12 currency pairs, including MXN**.
- **Transactions per customer:** a median of 5 in six months (the busiest 10% have 11 or more), so "my recent movements" lists stay short.
- **Transaccional contacts:** 85% by phone, median wait **118 s**, median call **205 s**, 91.5% resolved by agents today. That's the baseline.

## A. Answers the system can give automatically (read-only)

| # | What the customer asks | Data used | Quality |
|---|---|---|---|
| 1 | **"Did my payment/transfer go through?"**: find the transaction by date, amount, merchant or type, then give its status | `transactions` | ✅ Strong |
| 2 | **"Why was it declined?"**: code 51 = insufficient funds, 14 = invalid card, 05 = do not honor, 54 = expired card | `response_code` | ⚠️ Report the code as the bank's record. The codes don't match the product data, so don't add explanations beyond them |
| 3 | **"Why is it pending?" / "What does reversed mean?"** | `transaction_status` + a policy text the team writes | ✅ The policy is synthetic, so label it that way |
| 4 | **"My recent movements"**, filtered by type, merchant, category, channel, country or amount | `transactions` | ✅ Strong |
| 5 | **"How much did I spend on food this month?"** | `transaction_category` (filled for 95% of purchases and payments) | ✅ Good |
| 6 | **"What's my balance / available credit?"** Available credit = limit − balance | `products` (credit limit filled for 95% of credit cards and loans) | ⚠️ Balances are a current snapshot, not the balance at the time of each transaction |
| 7 | **"How much is that in dollars/pesos?"**, using the rate on the transaction's date, with buy and sell rates | `daily_exchange_rates` | ✅ Strong. Do the maths in code, never in the LLM |
| 8 | **"Where did this withdrawal happen?"**: the ATM or branch name and city | `branch_id` (filled for 95% of ATM and branch transactions) | ⚠️ Branch coordinates are broken, so use the name and city only |
| 9 | **"What's this adjustment on my loan?"** | Transaction type + product type | ✅ Good |
| 10 | **"When does my card expire?" / "What's my interest rate?"** | `expiration_date`, `interest_rate` | ✅ Covers 95% of cards and 90% of products |

## B. Actions that need the customer's confirmation

| Action | Example |
|---|---|
| **`open_case`** | "My transfer has been pending for 5 days" or "the reversal hasn't arrived". The customer confirms, the system creates the case, reads it back to check it exists, then gives the case number |
| *Optional:* **temporarily freeze the card** | After an unrecognised charge. It can be undone and doesn't move money, so it makes a great "confirm → act → verify" demo, but it drifts toward card support |

## C. Cases that go to a human (with the handoff JSON)

| Trigger | Data behind it |
|---|---|
| Unrecognised charge or suspected fraud | `fraud_score`: median 48.6 for fraud vs 15.0 otherwise. Also foreign transactions: 3.7% are in the USA, Spain or Brazil |
| Blocked or suspended product | `product_status` (Blocked 5%, Suspended 2%) |
| Late payment | `days_past_due` (0, 15, 30, 60, 90, 120 or 180 days). The system can tell the customer, but negotiating debt is for a human |
| Unusually large amount | Above the 99th percentile for that currency (for example about US$9,500) |
| Repeat contact, anger, or a complaint | Previous records in `call_center_interactions` for the same customer, plus sentiment |
| Code 05 ("do not honor") | The code gives no reason, so the system can't explain the decline |

## D. Extra context that makes it feel smart

- **App errors:** in March 2025 alone there were about 4,700 errors on the `/payments`, `/transfer` and `/transactions` pages. If the customer asks "my payment didn't work", the system can say "I see an error in the app at 14:02 while you were paying".
    - ⚠️ There's no transaction ID in these events, only customer and time, so treat the match as a hint, not a fact.
- **Contact history:** "you contacted us about this 2 days ago" lets the system detect repeat contacts and escalate.
- **Foreign transactions:** Brazil appears in the data, which fits the Portuguese demo well.

## E. What the data can't support (list these as limitations)

- **Status history:** each transaction appears once with a single status, so you can't see a Pending one turn into Approved.
- **Balance at the time of a transaction:** only the current balance exists.
- **Past dispute outcomes:** complaints can't be linked to transactions.
- **Credit card statements:** there's no due date, minimum payment or closing date.
- **MXN:** Mexican products are in USD, although the exchange-rate table has MXN.
- **Portuguese:** none in the data.
- **Real intents:** transcripts are templates.
- **Uniform statuses:** declines are 5% for **every** transaction type and channel, so the data can't show that some channels fail more. Don't claim that in the analysis.

## Recommendation for the build

Don't implement everything. The judges reward depth, not the number of features. Build this core:

- **Answer automatically:** 1, 2, 3, 4, 6, 7.
- **Action:** `open_case` with confirmation.
- **Human:** unrecognised charge, blocked product, late payment.

That covers all three required paths (normal, ambiguous, human) and uses the data's strongest parts. Leave 5, 8, 9, 10 and the extra context in section D for later if there's time.
