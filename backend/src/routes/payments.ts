import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';
import { BillPaymentBody, CustomerParams, DryRunQuery, PixBody, TransferBody } from '../schemas.js';
import { executePayment, previewPayment, type Destination, type PaymentMethod } from '../services/payments.js';

interface CommonBody {
  source_product_id: string;
  amount: number;
  currency?: string;
  description?: string;
  category?: string;
}

function run(customerId: string, method: PaymentMethod, body: CommonBody & Destination, dryRun?: boolean) {
  const { source_product_id, amount, currency, description, category, ...destination } = body;
  const req = { customerId, sourceProductId: source_product_id, method, amount, currency, description, category, destination };
  return dryRun ? previewPayment(req) : executePayment(req);
}

const DESCRIPTION =
  'Transações negadas (saldo/limite insuficiente, produto bloqueado, cartão vencido, destino inválido) são gravadas ' +
  'com status Declined e o motivo. Erros de validação retornam 4xx sem gravar nada. Use ?dry_run=true para simular.';

export const paymentRoutes: FastifyPluginAsyncTypebox = async (app) => {
  app.post('/customers/:customerId/transfers', {
    schema: {
      tags: ['Operações'],
      summary: 'Transferência para conta do banco ou de outro banco (feature 2)',
      description: `${DESCRIPTION} Para outro banco, o país precisa ser um dos países do banco (México, Colômbia, Argentina); envios entre países mostram o valor convertido na moeda local do destino.`,
      params: CustomerParams,
      querystring: DryRunQuery,
      body: TransferBody,
    },
    handler: async (req, reply) =>
      reply.code(req.query.dry_run ? 200 : 201).send(await run(req.params.customerId, 'transfer', req.body, req.query.dry_run)),
  });

  app.post('/customers/:customerId/pix', {
    schema: {
      tags: ['Operações'],
      summary: 'Pix por chave: e-mail, celular ou documento (feature 2)',
      description: DESCRIPTION,
      params: CustomerParams,
      querystring: DryRunQuery,
      body: PixBody,
    },
    handler: async (req, reply) =>
      reply.code(req.query.dry_run ? 200 : 201).send(await run(req.params.customerId, 'pix', req.body, req.query.dry_run)),
  });

  app.post('/customers/:customerId/bill-payments', {
    schema: {
      tags: ['Operações'],
      summary: 'Pagamento de boleto/conta (feature 2)',
      description: DESCRIPTION,
      params: CustomerParams,
      querystring: DryRunQuery,
      body: BillPaymentBody,
    },
    handler: async (req, reply) =>
      reply.code(req.query.dry_run ? 200 : 201).send(await run(req.params.customerId, 'bill_payment', req.body, req.query.dry_run)),
  });
};
