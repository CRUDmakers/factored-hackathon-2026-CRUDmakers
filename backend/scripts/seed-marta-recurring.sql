-- Dados fictícios para demonstrar pagamentos recorrentes (GET /recurring-payments) com a cliente de teste
-- Marta Sánchez Romero (CLI-25NDK326VNE4), a partir da conta corrente 8115899730 (PRD-R0Z4WR0SCBJH).
--
-- 5 pagamentos repetidos em jul, ago e set/2026; a academia também já foi paga em 1º/out.
-- Com o mês de referência em outubro/2026: 4 aparecem como "due" e 1 como "paid".
-- Idempotente: apaga e recria as próprias linhas (IDs TRX-MARTAREC…). Não altera saldos.
--
--   docker exec -i banking-cs-ai-db-1 psql -U banking -d banking < backend/scripts/seed-marta-recurring.sql

BEGIN;

DELETE FROM transactions WHERE transaction_id LIKE 'TRX-MARTAREC%';

WITH payments (code, day, method, tx_type, category, merchant, amount, description, counterparty) AS (
  VALUES
    ('RENT', 3, 'transfer', 'Transfer', NULL, NULL, 1850000.00, 'Arriendo apartamento',
     '{"type": "external", "name": "Inmobiliaria del Caribe SAS", "account_number": "0012345678", "bank_name": "Bancolombia", "document_number": "900123456", "country": "Colombia", "international": false}'::jsonb),
    ('INET', 5, 'bill_payment', 'Payment', 'Services', 'Claro Hogar Internet', 89900.00, 'Internet fibra 300 Mbps',
     '{"type": "bill", "barcode": "41577099980000000000890000000000000001234500", "biller_name": "Claro Hogar Internet", "due_date": null, "paid_after_due_date": false, "international": false}'::jsonb),
    ('NFLX', 12, 'bill_payment', 'Payment', 'Entertainment', 'Netflix', 44900.00, 'Netflix Estándar',
     '{"type": "bill", "barcode": "41577099980000000000449000000000000002345600", "biller_name": "Netflix", "due_date": null, "paid_after_due_date": false, "international": false}'::jsonb),
    ('CLDE', 18, 'bill_payment', 'Payment', 'Services', 'Claude Pro (Anthropic)', 84000.00, 'Suscripción Claude Pro',
     '{"type": "bill", "barcode": "41577099980000000000840000000000000003456700", "biller_name": "Claude Pro (Anthropic)", "due_date": null, "paid_after_due_date": false, "international": false}'::jsonb),
    ('GYMS', 1, 'bill_payment', 'Payment', 'Health', 'Smart Fit', 99900.00, 'Plan Black Smart Fit',
     '{"type": "bill", "barcode": "41577099980000000000999000000000000004567800", "biller_name": "Smart Fit", "due_date": null, "paid_after_due_date": false, "international": false}'::jsonb)
),
months (month) AS (
  VALUES (7), (8), (9), (10)
),
rows AS (
  SELECT p.*, m.month, make_timestamp(2026, m.month, p.day, 13, 0, 0) AS paid_at
    FROM payments p CROSS JOIN months m
   WHERE m.month < 10 OR p.code = 'GYMS' -- em outubro só a academia já foi paga
)
INSERT INTO transactions (
  transaction_id, transaction_date, process_date, product_id, customer_id, transaction_type, transaction_category,
  amount, currency, amount_usd, channel, merchant_name, transaction_country, transaction_city,
  transaction_status, response_code, is_fraud, origin, payment_method, description, counterparty
)
SELECT
  'TRX-MARTAREC' || r.code || lpad(r.month::text, 2, '0'),
  r.paid_at,
  r.paid_at::date,
  'PRD-R0Z4WR0SCBJH',
  'CLI-25NDK326VNE4',
  r.tx_type,
  r.category,
  r.amount,
  'COP',
  round(r.amount * (
    SELECT x.exchange_rate FROM daily_exchange_rates x
     WHERE x.source_currency = 'COP' AND x.target_currency = 'USD'
     ORDER BY x.date DESC LIMIT 1
  ), 2),
  'App',
  r.merchant,
  'Colombia',
  'Barranquilla',
  'Approved',
  '00',
  false,
  'simulated',
  r.method,
  r.description,
  r.counterparty
FROM rows r;

COMMIT;

SELECT transaction_id, transaction_date::date AS day, payment_method, amount, coalesce(merchant_name, counterparty->>'name') AS destination
  FROM transactions WHERE transaction_id LIKE 'TRX-MARTAREC%' ORDER BY transaction_date;
