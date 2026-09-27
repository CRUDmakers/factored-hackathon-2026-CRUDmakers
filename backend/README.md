# Backend 1: dados e operações do Banco LATAM

API em **Fastify + TypeScript + Prisma (PostgreSQL)** que lê os dados do datathon e simula operações bancárias para o assistente de atendimento (Backend 2) e o frontend.

- Swagger UI: `http://localhost:3000/docs` (OpenAPI JSON em `/docs/json`)
- CORS liberado para qualquer origem, método e header
- Testes com 100% de cobertura (statements, branches, funções e linhas), rodando contra um Postgres real

## Como rodar (Docker)

Na raiz do repositório, com os CSVs em `./data` (veja o README principal):

```bash
docker compose up -d db
docker compose run --rm etl
docker compose up -d api
```

A carga (`etl`) aplica as migrações e copia os CSVs via `COPY` (4,4 mi de transações em cerca de 2 min). Ela só roda se o banco estiver vazio. Para recarregar do zero (o que apaga as operações simuladas):

```bash
docker compose run --rm etl sh -c "npx prisma migrate deploy && node dist/etl/cli.js --force"
```

Testes com cobertura, dentro do Docker e contra o banco `banking_test`:

```bash
docker compose run --rm test
```

## Desenvolvimento local

```bash
cd backend
npm install
npx prisma migrate deploy      # banco em DATABASE_URL (padrão: localhost:5432/banking)
npm run etl:dev                # carrega ../data
npm run dev                    # API com reload
npm run test:coverage          # usa TEST_DATABASE_URL (padrão: localhost:5432/banking_test)
npm run studio                 # Prisma Studio em http://localhost:5555 para navegar no banco
```

O Studio usa o `DATABASE_URL`. Com o Postgres do `docker compose`, o padrão (`localhost:5432/banking`) já funciona. Para abrir outro banco, passe a URL: `npm run studio -- --url postgresql://banking:banking@localhost:5432/banking_test`.

| Variável | Padrão | Uso |
|---|---|---|
| `DATABASE_URL` | `postgresql://banking:banking@localhost:5432/banking` | banco da API/ETL |
| `TEST_DATABASE_URL` | `postgresql://banking:banking@localhost:5432/banking_test` | banco dos testes (precisa terminar em `_test`) |
| `DATA_DIR` | `../data` | pasta dos CSVs |
| `PORT` / `HOST` | `3000` / `0.0.0.0` | servidor HTTP |
| `SCHEDULER_INTERVAL_MS` | `60000` | intervalo do executor de agendamentos |
| `LOG_LEVEL` | `info` | nível de log |

## Endpoints por feature

Todos os endpoints de cliente ficam em `/api/customers/{customerId}/…`.

| Feature | Endpoint |
|---|---|
| 1. Quanto dinheiro tenho (contas, fatura, limite, disponível) | `GET /balances` |
| 2. Transferência (no banco ou para outro banco em MX/CO/AR) | `POST /transfers` |
| 2. Pix por e-mail, celular ou documento | `POST /pix` |
| 2. Pagamento de boleto | `POST /bill-payments` |
| 3. Pagamentos agendados/recorrentes | `POST, GET /scheduled-payments`, `GET, PATCH, DELETE /scheduled-payments/{id}` |
| 4. Câmbio | `GET /api/exchange-rates`, `/convert`, `/history`, `/pairs` |
| 5. Status do pagamento e motivo da recusa | `GET /transactions/{id}/status` |
| 6. Últimas transações e relatório | `GET /transactions`, `GET /reports/transactions` |
| 7. Gastos por categoria (controle financeiro) | `GET /reports/spending` |
| 8. Onde aconteceu o saque (ATM/agência) | `GET /transactions/{id}` → `location` |
| 9. Ajuste no empréstimo | `GET /adjustments` |
| 10. Vencimento do cartão e taxa de juros | `GET /products`, `GET /products/{id}` |

Também há `GET /health`, `GET /api/reference` (países, moedas e códigos de resposta) e `POST /api/scheduled-payments/run`, que executa na hora os agendamentos vencidos.

## Regras da simulação

- **Origem**: transferência e Pix saem de conta corrente, poupança ou cartão de débito. Boleto aceita também cartão de crédito, que consome o limite e aumenta a fatura.
- **Recusas**: são gravadas como `Declined`, com o código ISO do dataset: `05` produto bloqueado/inativo, `14` destino inválido ou chave Pix não encontrada, `51` saldo/limite insuficiente, `54` cartão vencido. Erros de validação (destino ausente, país não atendido, código de barras inválido) retornam 4xx e não gravam nada.
- **Países**: transferências para outro banco só vão para México, Colômbia ou Argentina. Envios entre países trazem `destination_amount` na moeda local do destino.
- **Moedas**: o valor pode ser informado em outra moeda (`currency`) e é convertido pela cotação mais recente. Como o histórico de câmbio termina em 2026-06-17, a API usa a última cotação disponível.
- **Destino no banco**: creditar uma conta soma ao saldo; pagar cartão ou empréstimo reduz a dívida. O crédito gera uma transação `Deposit` para o dono do produto de destino.
- **`?dry_run=true`**: simula a operação (conversão, saldo resultante, recusa) sem gravar nada.
- **Relatórios**: sem datas, usam os 30 dias (transações) ou 90 dias (gastos) até a última transação do cliente, já que o dataset termina em 2026-06-17. Os valores são consolidados em USD.
- **Agendamentos**: o executor roda a cada `SCHEDULER_INTERVAL_MS` e usa `FOR UPDATE SKIP LOCKED`, então funciona com várias instâncias. `once` termina como `completed` ou `failed`. Recorrentes param em `max_executions` ou depois de `end_date`.
- Operações simuladas ficam na mesma tabela `transactions`, com `origin = 'simulated'`.

## Estrutura

```
prisma/            schema e migrações
src/
  app.ts           Fastify, CORS, Swagger, tratamento de erros
  main.ts          ponto de entrada (servidor + executor de agendamentos)
  db/prisma.ts     Prisma Client (adapter pg) e pool compartilhado
  etl/             carga dos CSVs via COPY
  routes/          rotas HTTP (schemas TypeBox → validação + Swagger)
  services/        regras de negócio
  lib/             domínio (países, produtos), erros, códigos ISO
tests/             Vitest + fixtures CSV (mini-dataset)
```

A cobertura exclui apenas o código gerado pelo Prisma e os dois arquivos de entrada do processo (`src/main.ts`, `src/etl/cli.ts`), que só chamam funções já testadas.
