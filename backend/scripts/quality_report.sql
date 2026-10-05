-- Relatório de qualidade dos dados carregados pelo ETL (somente leitura).
--   psql "$DATABASE_URL" -f backend/scripts/quality_report.sql
--   docker compose exec -T db psql -U banking -d banking < backend/scripts/quality_report.sql
-- Rejeições = linhas fora do contrato (não entram). Avisos = linhas que entram, mas com problema conhecido.

\echo '== Linhagem e rejeições por tabela (etl_files) =='
SELECT target_table, count(*) AS files, sum(rows_read) AS rows_read, sum(rows_loaded) AS rows_loaded,
       sum(rows_rejected) AS rows_rejected, min(partition_date) AS first_partition, max(partition_date) AS last_partition,
       max(loaded_at) AS last_load
  FROM etl_files GROUP BY 1 ORDER BY 1;

\echo '== Motivos de rejeição =='
SELECT target_table, r.key AS reason, sum(r.value::int) AS rows
  FROM etl_files, jsonb_each_text(rejects) r GROUP BY 1, 2 ORDER BY 1, 3 DESC;

\echo '== Atualidade (política: partição D carregada até D+1) =='
SELECT max(partition_date) AS latest_partition, current_date - max(partition_date) AS age_days,
       (current_date - max(partition_date)) <= 1 AS fresh
  FROM etl_files WHERE target_table = 'transactions';

\echo '== Partições faltando entre a primeira e a última =='
SELECT d::date AS missing_partition
  FROM generate_series((SELECT min(partition_date) FROM etl_files), (SELECT max(partition_date) FROM etl_files), interval '1 day') d
 WHERE d::date NOT IN (SELECT partition_date FROM etl_files WHERE partition_date IS NOT NULL);

\echo '== Avisos (carregados, mas com problema conhecido) =='
SELECT 'products sem cliente em customers' AS check, count(*) AS rows FROM products p
 WHERE NOT EXISTS (SELECT 1 FROM customers c WHERE c.customer_id = p.customer_id)
UNION ALL SELECT 'transactions sem cliente em customers', count(*) FROM transactions t
 WHERE t.origin = 'historical' AND NOT EXISTS (SELECT 1 FROM customers c WHERE c.customer_id = t.customer_id)
UNION ALL SELECT 'transactions sem produto em products', count(*) FROM transactions t
 WHERE t.origin = 'historical' AND t.product_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM products p WHERE p.product_id = t.product_id)
UNION ALL SELECT 'transactions com agência inexistente', count(*) FROM transactions t
 WHERE t.branch_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM branches b WHERE b.branch_id = t.branch_id)
UNION ALL SELECT 'transactions: transaction_date em outro dia que a partição (process_date)', count(*) FROM transactions
 WHERE origin = 'historical' AND transaction_date::date <> process_date
UNION ALL SELECT 'transactions em país onde o banco não opera', count(*) FROM transactions
 WHERE transaction_country NOT IN ('México', 'Colombia', 'Argentina')
UNION ALL SELECT 'transactions não-USD sem amount_usd', count(*) FROM transactions
 WHERE origin = 'historical' AND currency <> 'USD' AND amount_usd IS NULL
UNION ALL SELECT 'branches com coordenadas inválidas (perto de 0,0)', count(*) FROM branches
 WHERE abs(latitude) <= 1 AND abs(longitude) <= 1
UNION ALL SELECT 'contas (corrente/poupança) com número repetido', count(*) FROM (
  SELECT product_number FROM products WHERE product_type IN ('Cuenta Corriente', 'Cuenta Ahorro') AND product_number IS NOT NULL
   GROUP BY 1 HAVING count(*) > 1) d
UNION ALL SELECT 'customers com agência de cadastro inexistente', count(*) FROM customers c
 WHERE c.registration_branch_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM branches b WHERE b.branch_id = c.registration_branch_id)
UNION ALL SELECT 'customers sem e-mail', count(*) FROM customers WHERE email IS NULL;
