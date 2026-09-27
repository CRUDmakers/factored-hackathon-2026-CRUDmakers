/**
 * Clientes do dataset real escolhidos para a demo (consulta no Postgres local):
 * ativos, com conta corrente ativa, cartão de crédito e transações recentes (inclusive ATM e recusas).
 * `account` é o número de uma conta corrente ativa (único no dataset), usado como contato na transferência.
 */
export const TEST_CUSTOMERS = [
  { id: 'CLI-25NDK326VNE4', account: '8115899730', name: 'Marta Sánchez Romero', country: 'CO', note: { es: 'COP · 4 tarjetas · préstamo', pt: 'COP · 4 cartões · empréstimo' } },
  { id: 'CLI-EF70WD91TBJQ', account: '7684909661', name: 'Rosa Diana Herrera Sánchez', country: 'AR', note: { es: 'ARS + USD', pt: 'ARS + USD' } },
  { id: 'CLI-QITAGXCUR83U', account: '8015502428', name: 'Gabriela Campos Guerrero', country: 'MX', note: { es: 'USD · débito bloqueado', pt: 'USD · débito bloqueado' } },
  { id: 'CLI-7T6B34S2O9UL', account: '5052584234', name: 'Francisco Javier Sánchez', country: 'MX', note: { es: 'USD · 2 tarjetas de débito', pt: 'USD · 2 cartões de débito' } },
] as const;

/** Cliente suspenso: a API recusa a sessão (403 customer_inactive). Útil para demonstrar o erro. */
export const INACTIVE_TEST_CUSTOMER = 'CLI-CSV0VF8IA55L';
