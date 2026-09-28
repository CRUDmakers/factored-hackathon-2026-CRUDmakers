import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';
import { ConvertQuery, RateHistoryQuery, RateQuery } from '../schemas.js';
import { convert, getAvailablePairs, getRate, getRateHistory } from '../services/exchange.js';

export const exchangeRoutes: FastifyPluginAsyncTypebox = async (app) => {
  app.get('/exchange-rates', {
    schema: {
      tags: ['Câmbio'],
      summary: 'Cotação entre duas moedas (feature 4)',
      description: 'Usa a cotação mais recente até `date`. O histórico vai de 2023-06-17 a 2026-06-17.',
      querystring: RateQuery,
    },
    handler: (req) => getRate(req.query.from, req.query.to, req.query.date),
  });

  app.get('/exchange-rates/convert', {
    schema: { tags: ['Câmbio'], summary: 'Converte um valor para outra moeda (feature 4)', querystring: ConvertQuery },
    handler: (req) => convert(req.query.amount, req.query.from, req.query.to, req.query.date),
  });

  app.get('/exchange-rates/history', {
    schema: { tags: ['Câmbio'], summary: 'Histórico diário de uma cotação', querystring: RateHistoryQuery },
    handler: (req) => getRateHistory(req.query.from, req.query.to, req.query.start, req.query.end),
  });

  app.get('/exchange-rates/pairs', {
    schema: { tags: ['Câmbio'], summary: 'Pares de moedas disponíveis e período coberto' },
    handler: () => getAvailablePairs(),
  });
};
