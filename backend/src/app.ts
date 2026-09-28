import cors from '@fastify/cors';
import swagger from '@fastify/swagger';
import swaggerUi from '@fastify/swagger-ui';
import type { TypeBoxTypeProvider } from '@fastify/type-provider-typebox';
import Fastify, { type FastifyError, type FastifyServerOptions } from 'fastify';
import { registerAuth, securitySchemes } from './auth.js';
import { config } from './config.js';
import { AppError } from './lib/errors.js';
import { authRoutes } from './routes/auth.js';
import { customerRoutes } from './routes/customers.js';
import { exchangeRoutes } from './routes/exchange.js';
import { metaRoutes } from './routes/meta.js';
import { paymentRoutes } from './routes/payments.js';
import { scheduledRoutes } from './routes/scheduled.js';
import { transactionRoutes } from './routes/transactions.js';

export async function buildApp(options: FastifyServerOptions = {}) {
  // Em produção não há segredo padrão: sem eles a API não sobe.
  if (!config.authJwtSecret || !config.authServiceKey) {
    throw new Error('Defina AUTH_JWT_SECRET e AUTH_SERVICE_KEY (obrigatórios em produção).');
  }

  const app = Fastify({
    ...options,
    ajv: { customOptions: { coerceTypes: 'array', removeAdditional: false } },
  }).withTypeProvider<TypeBoxTypeProvider>();

  // CORS totalmente liberado: qualquer origem (refletida, então funciona com credentials), método e header
  // (os headers pedidos no preflight, como Authorization e x-service-key, são refletidos).
  await app.register(cors, {
    origin: true,
    credentials: true,
    methods: ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
    maxAge: 86_400,
  });

  // Aceita `content-type: application/json` com corpo vazio (comum em POST/DELETE vindos do frontend).
  app.removeContentTypeParser('application/json');
  app.addContentTypeParser('application/json', { parseAs: 'string' }, (_req, body, done) => {
    try {
      done(null, body === '' ? undefined : JSON.parse(body as string));
    } catch {
      done(Object.assign(new Error('JSON inválido no corpo da requisição.'), { statusCode: 400, code: 'invalid_json' }), undefined);
    }
  });

  // Antes do Swagger e das rotas: o onRoute marca a segurança de cada rota e o onRequest faz a checagem.
  registerAuth(app);

  await app.register(swagger, {
    openapi: {
      info: {
        title: 'Banco LATAM — Backend 1',
        description:
          'Leitura dos dados do banco e simulação de operações (transferências, Pix, boletos e agendamentos) ' +
          'para o assistente de atendimento. Clientes, produtos e transações vêm do dataset do Factored Datathon 2026.',
        version: '1.0.0',
      },
      components: { securitySchemes },
      tags: [
        { name: 'Autenticação', description: 'Serviço de identidade de TESTE (simulado), não é login real' },
        { name: 'Clientes' },
        { name: 'Produtos' },
        { name: 'Transações' },
        { name: 'Relatórios' },
        { name: 'Operações' },
        { name: 'Agendamentos' },
        { name: 'Câmbio' },
        { name: 'Meta' },
      ],
    },
  });
  await app.register(swaggerUi, { routePrefix: '/docs' });

  app.setErrorHandler((err: FastifyError, req, reply) => {
    if (err instanceof AppError) {
      return reply.code(err.statusCode).send({ error: err.code, message: err.message, details: err.details });
    }
    if (err.validation) {
      return reply.code(400).send({ error: 'validation_error', message: err.message });
    }
    // Erros de cliente do próprio Fastify (JSON malformado, content-type não suportado etc.).
    if (err.statusCode && err.statusCode < 500) {
      return reply.code(err.statusCode).send({ error: err.code, message: err.message });
    }
    req.log.error(err);
    return reply.code(500).send({ error: 'internal_error', message: 'Erro interno.' });
  });

  await app.register(metaRoutes);
  await app.register(authRoutes);
  for (const routes of [customerRoutes, transactionRoutes, paymentRoutes, scheduledRoutes, exchangeRoutes]) {
    await app.register(routes, { prefix: '/api' });
  }
  return app;
}
