import type { FastifyInstance, FastifyRequest } from 'fastify';
import { AppError } from './lib/errors.js';
import { SERVICE_KEY_HEADER, assertServiceKey, authenticate, type Session } from './services/auth.js';

/**
 * - customer: Bearer válido e `sub` igual ao `:customerId` da URL (padrão de /api/customers/…)
 * - session: qualquer Bearer válido (rotas de sessão, ex.: logout)
 * - service: chave de serviço no header x-service-key (operações internas)
 */
export type AuthMode = 'customer' | 'session' | 'service';

declare module 'fastify' {
  interface FastifyContextConfig {
    auth?: AuthMode;
  }
  interface FastifyRequest {
    auth?: Session;
  }
}

/** Toda rota em /api/customers/… é do cliente, a menos que a rota declare outro modo. */
export function authMode(url: string | undefined, declared: AuthMode | undefined): AuthMode | undefined {
  return declared ?? (url?.startsWith('/api/customers/') ? 'customer' : undefined);
}

const checks: Record<AuthMode, (req: FastifyRequest) => Promise<void>> = {
  async customer(req) {
    const session = await authenticate(req.headers.authorization);
    // 403 sem consultar o recurso: não revela se o outro cliente existe.
    if (session.sub !== (req.params as { customerId: string }).customerId) {
      throw new AppError(403, 'forbidden', 'Esta sessão não tem acesso aos dados deste cliente.');
    }
    req.auth = session;
  },
  async session(req) {
    req.auth = await authenticate(req.headers.authorization);
  },
  async service(req) {
    assertServiceKey(req.headers[SERVICE_KEY_HEADER]);
  },
};

const SECURITY: Record<AuthMode, Array<Record<string, string[]>>> = {
  customer: [{ bearerAuth: [] }],
  session: [{ bearerAuth: [] }],
  service: [{ serviceKey: [] }],
};

export const securitySchemes = {
  bearerAuth: {
    type: 'http',
    scheme: 'bearer',
    bearerFormat: 'JWT',
    description: 'Token da sessão de teste, emitido por POST /auth/test-sessions.',
  },
  serviceKey: {
    type: 'apiKey',
    in: 'header',
    name: SERVICE_KEY_HEADER,
    description: 'Chave do provedor de identidade de teste / operações internas (AUTH_SERVICE_KEY).',
  },
} as const;

/** Checagem central: um único onRequest decide pela rota; o onRoute só marca a rota no Swagger. */
export function registerAuth(app: FastifyInstance) {
  app.addHook('onRoute', (route) => {
    const mode = authMode(route.url, route.config?.auth);
    if (mode) route.schema = { ...route.schema, security: SECURITY[mode] };
  });
  app.addHook('onRequest', async (req) => {
    const mode = authMode(req.routeOptions.url, req.routeOptions.config.auth);
    if (mode) await checks[mode](req);
  });
}
