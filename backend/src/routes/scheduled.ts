import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';
import { CreateScheduleBody, CustomerParams, ScheduleListQuery, ScheduleParams, UpdateScheduleBody } from '../schemas.js';
import {
  cancelSchedule,
  createSchedule,
  getSchedule,
  listSchedules,
  runDueSchedules,
  updateSchedule,
} from '../services/scheduled.js';

export const scheduledRoutes: FastifyPluginAsyncTypebox = async (app) => {
  app.post('/customers/:customerId/scheduled-payments', {
    schema: {
      tags: ['Agendamentos'],
      summary: 'Agenda um pagamento único ou recorrente (feature 3)',
      description:
        'O executor roda periodicamente e efetiva os agendamentos vencidos. `destination` segue o formato do método: ' +
        'to_product_id/beneficiary (transfer), pix_key (pix) ou barcode (bill_payment).',
      params: CustomerParams,
      body: CreateScheduleBody,
    },
    handler: async (req, reply) => reply.code(201).send(await createSchedule(req.params.customerId, req.body)),
  });

  app.get('/customers/:customerId/scheduled-payments', {
    schema: { tags: ['Agendamentos'], summary: 'Lista os agendamentos', params: CustomerParams, querystring: ScheduleListQuery },
    handler: (req) => listSchedules(req.params.customerId, req.query.status),
  });

  app.get('/customers/:customerId/scheduled-payments/:scheduledPaymentId', {
    schema: { tags: ['Agendamentos'], summary: 'Detalhe do agendamento e execuções', params: ScheduleParams },
    handler: (req) => getSchedule(req.params.customerId, req.params.scheduledPaymentId),
  });

  app.patch('/customers/:customerId/scheduled-payments/:scheduledPaymentId', {
    schema: {
      tags: ['Agendamentos'],
      summary: 'Pausa, retoma ou altera um agendamento',
      params: ScheduleParams,
      body: UpdateScheduleBody,
    },
    handler: (req) => updateSchedule(req.params.customerId, req.params.scheduledPaymentId, req.body),
  });

  app.delete('/customers/:customerId/scheduled-payments/:scheduledPaymentId', {
    schema: { tags: ['Agendamentos'], summary: 'Cancela um agendamento', params: ScheduleParams },
    handler: (req) => cancelSchedule(req.params.customerId, req.params.scheduledPaymentId),
  });

  app.post('/scheduled-payments/run', {
    config: { auth: 'service' },
    schema: {
      tags: ['Agendamentos'],
      summary: 'Executa agora os agendamentos vencidos (o executor já faz isso periodicamente)',
      description: 'Operação interna: exige a chave de serviço no header x-service-key.',
    },
    handler: async () => ({ executed: await runDueSchedules() }),
  });
};
