import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';
import { CustomerParams, ProductParams, ProductsQuery } from '../schemas.js';
import { getBalances, getCustomer, getProduct, listProducts, presentProduct } from '../services/customers.js';

export const customerRoutes: FastifyPluginAsyncTypebox = async (app) => {
  app.get('/customers/:customerId', {
    schema: { tags: ['Clientes'], summary: 'Dados básicos do cliente', params: CustomerParams },
    handler: (req) => getCustomer(req.params.customerId),
  });

  app.get('/customers/:customerId/balances', {
    schema: {
      tags: ['Clientes'],
      summary: 'Quanto dinheiro o cliente tem (feature 1)',
      description:
        'Saldo das contas, fatura/limite/disponível dos cartões de crédito, empréstimos, investimentos e totais por moeda, com patrimônio líquido em USD.',
      params: CustomerParams,
    },
    handler: (req) => getBalances(req.params.customerId),
  });

  app.get('/customers/:customerId/products', {
    schema: {
      tags: ['Produtos'],
      summary: 'Produtos do cliente: vencimento, taxa de juros, limite (feature 10)',
      params: CustomerParams,
      querystring: ProductsQuery,
    },
    handler: async (req) => (await listProducts(req.params.customerId, req.query)).map(presentProduct),
  });

  app.get('/customers/:customerId/products/:productId', {
    schema: { tags: ['Produtos'], summary: 'Detalhe de um produto (ex.: "quando meu cartão vence?")', params: ProductParams },
    handler: async (req) => presentProduct(await getProduct(req.params.customerId, req.params.productId)),
  });
};
