# Fixture de teste: segunda entrega (carga incremental)

Dados **sintéticos, feitos à mão para o teste** `tests/etl.test.ts`. Não vêm do dataset do datathon.
Simulam uma nova entrega do provedor, copiada por cima de `../data/`:

| Arquivo | O que simula | Resultado esperado |
|---|---|---|
| `day=17/transactions_20260617.csv` | Partição reenviada com correção: TRX-T06 passou de `Pending` para `Approved` e TRX-T16 foi removida | só essa partição é recarregada; TRX-T16 some, TRX-T06 fica `Approved` |
| `day=18/transactions_20260618.csv` | Partição nova com 2 linhas boas e 4 ruins | 2 carregadas; rejeitadas: `currency` (EUR), `amount` (não numérico), `partition` (process_date de outro dia), `duplicate_key` (TRX-T01 já existe) |

As demais partições e as dimensões não mudam (mesmo sha256) e são puladas.
