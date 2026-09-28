# Frontend: internet banking de demonstração do Banco LATAM

SPA em **Vite + React + TypeScript** que simula um cliente usando o internet banking do Banco LATAM (México, Colômbia e Argentina). Consome a API do Backend 1 (`../backend`). Não usa biblioteca de UI: o CSS é próprio (`src/styles.css`) e o gráfico é feito com CSS e SVG.

A interface é bilíngue, **espanhol / português**, com seletor no topo. A escolha fica salva no `localStorage`.

## Telas

| Tela | Endpoints |
|---|---|
| Login de demonstração | `POST /auth/test-sessions` (chave de serviço) |
| Início: contas, cartões de crédito (fatura, limite, disponível, uso) e empréstimos | `GET /balances`, `GET /customers/{id}` |
| Extrato com filtros (datas, tipo, status, canal) e paginação; detalhe com status, motivo e local (ATM/agência) | `GET /transactions`, `GET /transactions/{id}` |
| Pagar/Transferir: transferência (no banco ou outro banco), Pix e boleto | `POST /transfers`, `/pix`, `/bill-payments` |
| Agendamentos: listar, criar, pausar/retomar, cancelar | `GET/POST /scheduled-payments`, `PATCH/DELETE /scheduled-payments/{id}` |
| Relatórios: gastos por categoria e por mês | `GET /reports/spending` |
| Câmbio: conversor | `GET /api/exchange-rates/convert` |
| Assistente (em breve) | nenhum: painel reservado para o chat do Backend 2 |

**Confirmação em duas etapas.** Toda operação de Pagar/Transferir primeiro chama o endpoint com `?dry_run=true` e mostra a prévia: valor debitado, câmbio, saldo resultante, valor que o favorecido recebe e a recusa prevista. Só o botão "Confirmar" envia a operação de verdade. Depois aparece o comprovante com o status real e um link para o detalhe no extrato.

## Autenticação (serviço de identidade de TESTE)

O login é **simulado** e a tela avisa isso ("ambiente de demonstração"). O usuário digita ou escolhe um `customer_id` e o frontend chama `POST /auth/test-sessions` com o header `x-service-key`. A API devolve um JWT curto (15 min por padrão) e todas as rotas `/api/customers/{id}/…` passam a receber `Authorization: Bearer <token>`.

- O token fica em memória e no `sessionStorage`, que some ao fechar a aba.
- `401 session_expired`, ou o relógio local passar de `expires_at`, leva de volta ao login com "Sua sessão expirou". Outros 401 (`unauthorized`, `session_revoked`) também voltam ao login.
- `403 forbidden` mostra "Acesso negado".
- "Sair" chama `DELETE /auth/sessions/current`.

> **A chave de serviço dentro do frontend só é aceitável nesta demo.** Qualquer variável `VITE_*` vai para o bundle público, então qualquer pessoa pode lê-la e emitir sessões para qualquer cliente. Em produção, quem emite a sessão é um provedor de identidade de verdade (login com senha/MFA) e a chave nunca chega ao navegador.

Todo o contrato HTTP está em `src/api.ts`. Se a autenticação mudar, ajuste apenas `startSession`, `endSession` e o tratamento de 401/403 nesse arquivo.

## Clientes de teste

São atalhos na tela de login (`src/testCustomers.ts`), escolhidos no dataset real: clientes ativos com conta corrente ativa, cartão de crédito e transações recentes, incluindo saques em ATM e recusas.

| ID | Cliente | Destaque |
|---|---|---|
| `CLI-25NDK326VNE4` | Marta Sánchez Romero (CO) | COP, 4 cartões (um vencido, recusa `54` no boleto), empréstimo |
| `CLI-EF70WD91TBJQ` | Rosa Diana Herrera Sánchez (AR) | contas em ARS e USD |
| `CLI-QITAGXCUR83U` | Gabriela Campos Guerrero (MX) | cartão de débito bloqueado (recusa `05`) |
| `CLI-7T6B34S2O9UL` | Francisco Javier Sánchez (MX) | vários produtos em USD |

`CLI-CSV0VF8IA55L` está suspenso: o login mostra o erro `customer_inactive`.

Para testar Pix, use a chave `gabrielacampos@gmail.com`. É única no dataset, e a prévia mostra quem recebe.

## Como rodar

### Docker (na raiz do repositório)

```bash
docker compose up -d db api        # a API precisa estar de pé
docker compose up -d --build frontend
# http://localhost:5173
```

O container faz o build do Vite e serve os arquivos estáticos com nginx. As variáveis `VITE_*` entram no bundle **na hora do build** e são usadas pelo navegador. Por isso o padrão é `http://localhost:3000`. Para apontar para outra API:

```bash
FRONTEND_API_URL=http://minha-api:3000 FRONTEND_SERVICE_KEY=outra-chave docker compose up -d --build frontend
```

### Desenvolvimento local

```bash
cd frontend
npm install
cp .env.example .env    # opcional
npm run dev             # http://localhost:5173
npm run typecheck
npm run build           # typecheck + build em dist/
```

| Variável | Padrão | Uso |
|---|---|---|
| `VITE_API_URL` | `http://localhost:3000` | URL do Backend 1 vista pelo navegador |
| `VITE_SERVICE_KEY` | `dev-service-key` | chave do provedor de identidade de teste (só para a demo) |

## Limitações

- O login não é real. Veja a seção de autenticação.
- A API responde em pt-BR. Motivos de recusa e status conhecidos (`reason_code`) são traduzidos no frontend. Textos livres da API (ex.: `decline_detail` e mensagens de validação) aparecem em português também na interface em espanhol.
- O histórico termina em 2026-06-17. Operações simuladas feitas hoje mudam a "última transação" do cliente, e o relatório sem datas passa a cobrir só elas. O botão "90 dias do histórico" fixa o período nos dados reais.
- O câmbio usa a última cotação disponível (2026-06-17).
- O assistente é só um espaço reservado. Nenhuma chamada é feita até o Backend 2 existir.
- Sem testes automatizados de UI. A verificação foi manual, no navegador.

## Estrutura

```
src/
  api.ts            cliente HTTP, sessão (token, 401/403) e tipos das respostas
  i18n.ts           dicionários es/pt e contexto de idioma
  ui.tsx            formatação, useAsync, Loading/ErrorBox/StatusBadge, seletor de idioma
  App.tsx           casca: topo, navegação por hash, contador da sessão, assistente
  testCustomers.ts  atalhos do login
  pages/            Login, Home, Statement, Pay, PaymentForm, Schedules, Reports, Exchange, Assistant
Dockerfile          build (node) + nginx
nginx.conf          SPA fallback e cache dos assets
```
