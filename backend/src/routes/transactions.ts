import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';
import { AdjustmentsQuery, CustomerParams, PeriodQuery, TransactionParams, TransactionsQuery } from '../schemas.js';
import {
  getAdjustments,
  getReport,
  getSpending,
  getTransaction,
  getTransactionStatus,
  listTransactions,
} from '../services/transactions.js';

export const transactionRoutes: FastifyPluginAsyncTypebox = async (app) => {
  app.get('/customers/:customerId/transactions', {
    schema: {
      tags: ['Transações'],
      summary: 'Últimas transações, com filtros (feature 6)',
      params: CustomerParams,
      querystring: TransactionsQuery,
    },
    handler: (req) => listTransactions(req.params.customerId, req.query),
  });

  app.get('/customers/:customerId/transactions/:transactionId', {
    schema: {
      tags: ['Transações'],
      summary: 'Detalhe da transação, com status e local: ATM/agência (features 5 e 8)',
      params: TransactionParams,
    },
    handler: (req) => getTransaction(req.params.customerId, req.params.transactionId),
  });

  app.get('/customers/:customerId/transactions/:transactionId/status', {
    schema: {
      tags: ['Transações'],
      summary: 'Status do pagamento: concluído, negado e por quê (feature 5)',
      params: TransactionParams,
    },
    handler: (req) => getTransactionStatus(req.params.customerId, req.params.transactionId),
  });

  app.get('/customers/:customerId/reports/transactions', {
    schema: {
      tags: ['Relatórios'],
      summary: 'Relatório de transações do período (feature 6)',
      description: 'Sem datas: 30 dias até a última transação do cliente. Valores consolidados em USD.',
      params: CustomerParams,
      querystring: PeriodQuery,
    },
    handler: (req) => getReport(req.params.customerId, req.query),
  });

  app.get('/customers/:customerId/reports/spending', {
    schema: {
      tags: ['Relatórios'],
      summary: 'Gastos por categoria e por mês: controle financeiro (feature 7)',
      description: 'Sem datas: 90 dias até a última transação do cliente. Valores em USD.',
      params: CustomerParams,
      querystring: PeriodQuery,
    },
    handler: (req) => getSpending(req.params.customerId, req.query),
  });

  app.get('/customers/:customerId/adjustments', {
    schema: {
      tags: ['Transações'],
      summary: 'Ajustes em empréstimos: "o que é esse ajuste?" (feature 9)',
      params: CustomerParams,
      querystring: AdjustmentsQuery,
    },
    handler: (req) => getAdjustments(req.params.customerId, req.query),
  });
};
