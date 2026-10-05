import { createSigner, type SignerOptions } from 'fast-jwt';
import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { buildApp } from '../src/app.js';
import { config } from '../src/config.js';
import { prisma } from '../src/db/prisma.js';
import { TOKEN_ISSUER } from '../src/services/auth.js';
import { ANA, BRUNO, DIEGO, SERVICE, UNKNOWN, balanceOf, bearer, resetData, testApp } from './helpers.js';

let app: FastifyInstance;
beforeAll(async () => {
  await resetData();
  app = await testApp();
});
afterAll(() => app.close());

const CHK = 'PRD-ANACHK000001';
const issue = (customer_id: string, headers: Record<string, string> = SERVICE) =>
  app.inject({ method: 'POST', url: '/auth/test-sessions', headers, payload: { customer_id } });
const balances = (headers: Record<string, string> = {}, customer = ANA) =>
  app.inject({ url: `/api/customers/${customer}/balances`, headers });

/** Assina um token com outras opções (chave, algoritmo, emissor), para simular tokens forjados. */
const forged = (options: Partial<SignerOptions & { key: string }>) =>
  `Bearer ${createSigner({ iss: TOKEN_ISSUER, sub: ANA, jti: 'x', expiresIn: 60_000, ...options })({})}`;

describe('emissão de sessão de teste', () => {
  it('emite um token que dá acesso aos dados do próprio cliente', async () => {
    const res = await issue(ANA);
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body).toMatchObject({ token_type: 'Bearer', expires_in: 900, customer_id: ANA, session_id: expect.any(String) });
    const ttl = new Date(body.expires_at).getTime() - Date.now();
    expect(ttl).toBeGreaterThan(890_000);
    expect(ttl).toBeLessThanOrEqual(900_000);

    const auth = { authorization: `Bearer ${body.access_token}` };
    expect((await balances(auth)).statusCode).toBe(200);
    const current = await app.inject({ url: '/auth/sessions/current', headers: auth });
    expect(current.json()).toEqual({ customer_id: ANA, session_id: body.session_id, expires_at: body.expires_at });
  });

  it.each([
    ['sem chave de serviço', {}],
    ['com chave errada', { 'x-service-key': 'errada' }],
  ])('401 %s', async (_, headers) => {
    const res = await issue(ANA, headers);
    expect(res.statusCode).toBe(401);
    expect(res.json()).toMatchObject({ error: 'unauthorized' });
  });

  it('recusa cliente inexistente, inativo ou ID fora do formato', async () => {
    expect((await issue(UNKNOWN)).json()).toMatchObject({ error: 'not_found' });

    await prisma.customer.update({ where: { customer_id: DIEGO }, data: { customer_status: 'Blocked' } });
    try {
      const res = await issue(DIEGO);
      expect(res.statusCode).toBe(403);
      expect(res.json()).toMatchObject({ error: 'customer_inactive' });
    } finally {
      await prisma.customer.update({ where: { customer_id: DIEGO }, data: { customer_status: 'Active' } });
    }

    expect((await issue('abc')).statusCode).toBe(400);
  });

  it('com lista de clientes liberados, recusa quem está fora dela antes de olhar o banco', async () => {
    config.authAllowedCustomers = [ANA];
    try {
      expect((await issue(ANA)).statusCode).toBe(201);
      for (const id of [BRUNO, UNKNOWN]) {
        const res = await issue(id);
        expect(res.statusCode).toBe(403);
        expect(res.json()).toMatchObject({ error: 'customer_not_allowed' });
      }
    } finally {
      config.authAllowedCustomers = [];
    }
  });
});

describe('rotas do cliente exigem sessão', () => {
  it.each([
    ['sem header', {}],
    ['esquema errado', { authorization: 'Basic YW5hOnNlbmhh' }],
    ['Bearer sem token', { authorization: 'Bearer' }],
    ['token malformado', { authorization: 'Bearer nao.e.jwt' }],
    ['assinatura inválida', { authorization: forged({ key: 'outro-segredo' }) }],
    ['algoritmo none', { authorization: forged({ algorithm: 'none' }) }],
    ['outro emissor', { authorization: forged({ key: config.authJwtSecret, iss: 'outro-idp' }) }],
  ])('401 unauthorized: %s', async (_, headers) => {
    const res = await balances(headers);
    expect(res.statusCode).toBe(401);
    expect(res.json()).toMatchObject({ error: 'unauthorized' });
  });

  it('401 session_expired para token expirado', async () => {
    const res = await balances(bearer(ANA, Date.now() - 2 * config.authSessionTtlSeconds * 1000));
    expect(res.statusCode).toBe(401);
    expect(res.json()).toMatchObject({ error: 'session_expired' });
  });

  it('403 ao acessar outro cliente, sem revelar se ele existe', async () => {
    const other = await balances(bearer(BRUNO));
    const missing = await balances(bearer(BRUNO), UNKNOWN);
    for (const res of [other, missing]) {
      expect(res.statusCode).toBe(403);
      expect(res.json()).toEqual({ error: 'forbidden', message: 'Esta sessão não tem acesso aos dados deste cliente.' });
    }
  });

  it('403 também para operações: nada é executado', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/customers/${ANA}/transfers`,
      headers: bearer(BRUNO),
      payload: { source_product_id: CHK, amount: 100, to_product_id: 'PRD-BRUCHK000001' },
    });
    expect(res.statusCode).toBe(403);
    expect(await balanceOf(CHK)).toBe(1000);

    const schedules = await app.inject({ method: 'DELETE', url: `/api/customers/${ANA}/scheduled-payments/SCH-X`, headers: bearer(BRUNO) });
    expect(schedules.statusCode).toBe(403);
  });
});

describe('logout', () => {
  it('revoga a sessão e limpa revogações expiradas', async () => {
    await prisma.revokedSession.create({ data: { jti: 'velho', customer_id: ANA, expires_at: new Date(Date.now() - 1000) } });
    const auth = { authorization: `Bearer ${(await issue(ANA)).json().access_token}` };

    const res = await app.inject({ method: 'DELETE', url: '/auth/sessions/current', headers: auth });
    expect(res.statusCode).toBe(204);
    expect(await prisma.revokedSession.findUnique({ where: { jti: 'velho' } })).toBeNull();

    for (const after of [await balances(auth), await app.inject({ url: '/auth/sessions/current', headers: auth })]) {
      expect(after.statusCode).toBe(401);
      expect(after.json()).toMatchObject({ error: 'session_revoked' });
    }
  });

  it('401 sem sessão', async () => {
    expect((await app.inject({ method: 'DELETE', url: '/auth/sessions/current' })).statusCode).toBe(401);
  });
});

describe('operações internas e rotas públicas', () => {
  it('POST /api/scheduled-payments/run exige a chave de serviço', async () => {
    const run = (headers: Record<string, string>) => app.inject({ method: 'POST', url: '/api/scheduled-payments/run', headers });
    expect((await run({})).json()).toMatchObject({ error: 'unauthorized' });
    expect((await run({ 'x-service-key': 'errada' })).statusCode).toBe(401);
    expect((await run(bearer(ANA))).statusCode).toBe(401); // sessão de cliente não serve
    expect((await run(SERVICE)).json()).toEqual({ executed: [] });
  });

  it.each(['/health', '/api/reference', '/api/exchange-rates/pairs', '/docs/json'])('%s continua público', async (url) => {
    expect((await app.inject(url)).statusCode).toBe(200);
  });

  it('rota inexistente dá 404, não 401', async () => {
    expect((await app.inject('/nao-existe')).statusCode).toBe(404);
  });

  it('preflight CORS de rota protegida passa sem token e libera o Authorization', async () => {
    const res = await app.inject({
      method: 'OPTIONS',
      url: `/api/customers/${ANA}/balances`,
      headers: { origin: 'http://localhost:5173', 'access-control-request-method': 'GET', 'access-control-request-headers': 'authorization' },
    });
    expect(res.statusCode).toBe(204);
    expect(res.headers['access-control-allow-headers']).toBe('authorization');
  });

  it('marca a segurança das rotas no Swagger', async () => {
    const spec = (await app.inject('/docs/json')).json();
    expect(Object.keys(spec.components.securitySchemes)).toEqual(['bearerAuth', 'serviceKey']);
    expect(spec.paths['/api/customers/{customerId}/balances'].get.security).toEqual([{ bearerAuth: [] }]);
    expect(spec.paths['/auth/sessions/current'].delete.security).toEqual([{ bearerAuth: [] }]);
    expect(spec.paths['/auth/test-sessions'].post.security).toEqual([{ serviceKey: [] }]);
    expect(spec.paths['/api/scheduled-payments/run'].post.security).toEqual([{ serviceKey: [] }]);
    expect(spec.paths['/health'].get.security).toBeUndefined();
    expect(spec.paths['/api/exchange-rates'].get.security).toBeUndefined();
  });
});

describe('configuração', () => {
  it('não sobe sem os segredos (caso de produção)', async () => {
    const secret = config.authJwtSecret;
    config.authJwtSecret = '';
    try {
      await expect(buildApp({ logger: false })).rejects.toThrow(/AUTH_JWT_SECRET/);
    } finally {
      config.authJwtSecret = secret;
    }
  });
});
