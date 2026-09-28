import { Type, type FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';
import { CustomerParams } from '../schemas.js';
import { describeSession, issueTestSession, revokeSession } from '../services/auth.js';

const SIMULATION =
  'Provedor de identidade SIMULADO para testes e demo (não é login real). Quem apresenta a chave de serviço ' +
  'faz o papel do provedor confiável que já verificou o cliente; a API só emite o token.';

export const authRoutes: FastifyPluginAsyncTypebox = async (app) => {
  app.post('/auth/test-sessions', {
    config: { auth: 'service' },
    schema: {
      tags: ['Autenticação'],
      summary: 'Emite uma sessão de teste para um cliente ativo',
      description: `${SIMULATION} O token é um JWT HS256 com sub = customer_id e expiração curta (AUTH_SESSION_TTL_SECONDS).`,
      body: Type.Object({ customer_id: CustomerParams.properties.customerId }),
    },
    handler: async (req, reply) => reply.code(201).send(await issueTestSession(req.body.customer_id)),
  });

  app.get('/auth/sessions/current', {
    config: { auth: 'session' },
    schema: { tags: ['Autenticação'], summary: 'Dados da sessão atual (cliente e expiração)' },
    handler: (req) => describeSession(req.auth!),
  });

  app.delete('/auth/sessions/current', {
    config: { auth: 'session' },
    schema: { tags: ['Autenticação'], summary: 'Encerra a sessão atual (logout)' },
    handler: async (req, reply) => {
      await revokeSession(req.auth!);
      return reply.code(204).send();
    },
  });
};
