import { beforeAll, describe, expect, it } from 'vitest';
import { buildApp } from '../src/app.js';
import { start } from '../src/server.js';
import { ANA, SERVICE, bearer, resetData, testApp } from './helpers.js';

beforeAll(resetData);

describe('app', () => {
  it('health e referência', async () => {
    const app = await testApp();
    expect((await app.inject('/health')).json()).toEqual({ status: 'ok' });
    const ref = (await app.inject('/api/reference')).json();
    expect(ref.countries).toEqual([
      { country: 'México', currency: 'MXN' },
      { country: 'Colombia', currency: 'COP' },
      { country: 'Argentina', currency: 'ARS' },
    ]);
    expect(ref.response_codes).toContainEqual(expect.objectContaining({ code: '51', reason_code: 'insufficient_funds' }));
    await app.close();
  });

  it('publica o Swagger com todas as rotas', async () => {
    const app = await testApp();
    const spec = (await app.inject('/docs/json')).json();
    expect(spec.openapi).toMatch(/^3\./);
    expect(Object.keys(spec.paths)).toEqual(
      expect.arrayContaining([
        '/api/customers/{customerId}/balances',
        '/api/customers/{customerId}/transfers',
        '/api/customers/{customerId}/pix',
        '/api/customers/{customerId}/bill-payments',
        '/api/customers/{customerId}/scheduled-payments',
        '/api/exchange-rates/convert',
      ]),
    );
    expect((await app.inject('/docs')).statusCode).toBeLessThan(400);
    await app.close();
  });

  it('libera CORS para qualquer origem, método e header', async () => {
    const app = await testApp();
    const res = await app.inject({
      method: 'OPTIONS',
      url: '/api/reference',
      headers: {
        origin: 'http://qualquer.site:5173',
        'access-control-request-method': 'DELETE',
        'access-control-request-headers': 'authorization,x-custom',
      },
    });
    expect(res.statusCode).toBe(204);
    expect(res.headers['access-control-allow-origin']).toBe('http://qualquer.site:5173');
    expect(res.headers['access-control-allow-credentials']).toBe('true');
    expect(res.headers['access-control-allow-methods']).toContain('DELETE');
    expect(res.headers['access-control-allow-headers']).toBe('authorization,x-custom');
    await app.close();
  });

  it('aceita JSON vazio e rejeita JSON malformado com 400', async () => {
    const app = await testApp();
    const empty = await app.inject({
      method: 'POST',
      url: '/api/scheduled-payments/run',
      headers: { 'content-type': 'application/json', ...SERVICE },
      payload: '',
    });
    expect(empty.statusCode).toBe(200);
    expect(empty.json()).toEqual({ executed: [] });

    const broken = await app.inject({
      method: 'POST',
      url: '/api/scheduled-payments/run',
      headers: { 'content-type': 'application/json', ...SERVICE },
      payload: '{nope',
    });
    expect(broken.statusCode).toBe(400);
    expect(broken.json()).toEqual({ error: 'invalid_json', message: 'JSON inválido no corpo da requisição.' });
    await app.close();
  });

  it('erros 4xx do Fastify mantêm o status', async () => {
    const app = await testApp();
    const res = await app.inject({
      method: 'POST',
      url: `/api/customers/${ANA}/pix`,
      headers: { 'content-type': 'text/xml', ...bearer(ANA) },
      payload: '<x/>',
    });
    expect(res.statusCode).toBe(415);
    expect(res.json().error).toBe('FST_ERR_CTP_INVALID_MEDIA_TYPE');
    await app.close();
  });

  it('erros inesperados viram 500 sem vazar detalhes', async () => {
    const app = await buildApp({ logger: false });
    app.get('/boom', async () => {
      throw new Error('segredo interno');
    });
    const res = await app.inject('/boom');
    expect(res.statusCode).toBe(500);
    expect(res.json()).toEqual({ error: 'internal_error', message: 'Erro interno.' });
    await app.close();
  });

  it('sobe e derruba o servidor HTTP', async () => {
    const server = await start({ port: 0, host: '127.0.0.1', schedulerIntervalMs: 60_000 });
    const address = server.app.server.address();
    expect(typeof address === 'object' && address?.port).toBeGreaterThan(0);
    await server.stop();
  });

  it('usa porta, host e intervalo da configuração quando não informados', async () => {
    const { config } = await import('../src/config.js');
    config.port = 0;
    config.host = '127.0.0.1';
    const server = await start();
    expect(server.app.server.listening).toBe(true);
    await server.stop();
  });
});
