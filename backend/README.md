# Backend 1: dados e operações do Banco LATAM

API em **Fastify + TypeScript + Prisma (PostgreSQL)** que lê os dados do datathon e simula operações bancárias para o assistente de atendimento (Backend 2) e o frontend.

- Swagger UI: `http://localhost:3000/docs` (OpenAPI JSON em `/docs/json`)
- CORS liberado para qualquer origem, método e header (inclusive `Authorization` e `x-service-key`)
- Dados de cliente só com sessão: `Authorization: Bearer <token>` do próprio cliente (veja [Autenticação](#autenticação))
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
npm run db:reset               # volta o banco ao estado inicial: recarrega ../data e APAGA operações simuladas e agendamentos
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
| `AUTH_JWT_SECRET` | só fora de produção: `dev-only-jwt-secret-troque-em-producao` | segredo HMAC (HS256) dos tokens de sessão |
| `AUTH_SERVICE_KEY` | só fora de produção: `dev-service-key` | chave do provedor de identidade de teste e das operações internas (header `x-service-key`) |
| `AUTH_SESSION_TTL_SECONDS` | `900` (15 min) | validade do token de sessão |

Com `NODE_ENV=production` (caso da imagem Docker) não há valor padrão para `AUTH_JWT_SECRET` e `AUTH_SERVICE_KEY`: a API não sobe sem eles. O `docker-compose.yml` passa valores de demo, que podem ser sobrescritos por variáveis de ambiente ou por um `.env` na raiz.

## Autenticação

> **Serviço de identidade simulado.** Não existe login real (senha, OTP, biometria). `POST /auth/test-sessions` faz o papel de um provedor de identidade confiável: quem tem a chave de serviço (o frontend/demo) afirma que já verificou o cliente, e a API emite a sessão. Um número de documento ou `customer_id` sozinho não prova identidade; o que dá acesso é o token assinado.

1. O frontend/demo pede uma sessão para um cliente ativo, com a chave de serviço:

   ```bash
   curl -s -X POST http://localhost:3000/auth/test-sessions      -H "x-service-key: demo-service-key" -H "content-type: application/json"      -d '{"customer_id":"CLI-G4X2AMVD62NR"}'
   # {"access_token":"eyJ...","token_type":"Bearer","expires_in":900,"expires_at":"...","session_id":"...","customer_id":"CLI-G4X2AMVD62NR"}
   ```

   (`demo-service-key` é o valor do `docker-compose.yml`; rodando com `npm run dev`, o padrão é `dev-service-key`.)

2. Chamadas a `/api/customers/{customerId}/…` levam o token, e só funcionam para o próprio cliente:

   ```bash
   curl -s http://localhost:3000/api/customers/CLI-G4X2AMVD62NR/balances -H "Authorization: Bearer eyJ..."
   ```

3. `GET /auth/sessions/current` mostra cliente e expiração da sessão; `DELETE /auth/sessions/current` encerra a sessão (logout).

O token é um JWT HS256 com `iss = banking-cs-test-idp`, `sub = customer_id`, `jti` (id da sessão) e `exp` curto. A checagem é central (`src/auth.ts`): um hook `onRequest` protege toda rota em `/api/customers/…` antes da validação e do handler, e as rotas de sessão/serviço declaram o modo em `config.auth`. O logout grava o `jti` em `revoked_sessions` até o token expirar. A emissão é recusada para cliente inexistente (404) ou com `customer_status` diferente de `Active` (403).

| Situação | Status | `error` |
|---|---|---|
| Sem `Authorization`, formato errado, token malformado, assinatura/emissor/algoritmo inválidos | 401 | `unauthorized` |
| Token expirado | 401 | `session_expired` |
| Sessão encerrada por logout | 401 | `session_revoked` |
| Token de um cliente acessando outro `customerId` (exista ele ou não) | 403 | `forbidden` |
| Chave de serviço ausente ou errada (`/auth/test-sessions`, `/api/scheduled-payments/run`) | 401 | `unauthorized` |
| Emissão para cliente inativo | 403 | `customer_inactive` |

Continuam públicos: `/health`, `/api/reference`, `/api/exchange-rates/*` e `/docs`. `POST /api/scheduled-payments/run` é operação interna e exige `x-service-key`. No Swagger, use o botão **Authorize** (esquemas `bearerAuth` e `serviceKey`).

## Endpoints por feature

Todos os endpoints de cliente ficam em `/api/customers/{customerId}/…` e exigem a sessão do próprio cliente.

| Feature | Endpoint |
|---|---|
| 1. Quanto dinheiro tenho (contas, fatura, limite, disponível) | `GET /balances` |
| 2. Transferência (no banco ou para outro banco em MX/CO/AR) | `POST /transfers` |
| 2. Pix por e-mail, celular ou documento | `POST /pix` |
| 2. Pagamento de boleto | `POST /bill-payments` |
| 3. Pagamentos agendados/recorrentes | `POST, GET /scheduled-payments`, `GET, PATCH, DELETE /scheduled-payments/{id}` |
| 3. Pagamentos recorrentes mensais (o que falta pagar no mês) | `GET /recurring-payments?as_of=` |
| 4. Câmbio | `GET /api/exchange-rates`, `/convert`, `/history`, `/pairs` |
| 5. Status do pagamento e motivo da recusa | `GET /transactions/{id}/status` |
| 6. Últimas transações e relatório | `GET /transactions`, `GET /reports/transactions` |
| 7. Gastos por categoria (controle financeiro) | `GET /reports/spending` |
| 8. Onde aconteceu o saque (ATM/agência) | `GET /transactions/{id}` → `location` |
| 9. Ajuste no empréstimo | `GET /adjustments` |
| 10. Vencimento do cartão e taxa de juros | `GET /products`, `GET /products/{id}` |

Também há `GET /health`, `GET /api/reference` (países, moedas e códigos de resposta) e `POST /api/scheduled-payments/run` (exige `x-service-key`), que executa na hora os agendamentos vencidos.

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
  auth.ts          checagem central de sessão/chave de serviço (hooks onRoute + onRequest)
  main.ts          ponto de entrada (servidor + executor de agendamentos)
  db/prisma.ts     Prisma Client (adapter pg) e pool compartilhado
  etl/             carga dos CSVs via COPY
  routes/          rotas HTTP (schemas TypeBox → validação + Swagger)
  services/        regras de negócio
  lib/             domínio (países, produtos), erros, códigos ISO
tests/             Vitest + fixtures CSV (mini-dataset)
```

A cobertura exclui apenas o código gerado pelo Prisma e os dois arquivos de entrada do processo (`src/main.ts`, `src/etl/cli.ts`), que só chamam funções já testadas.
