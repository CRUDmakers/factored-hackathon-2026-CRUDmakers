import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';
import { prisma } from '../db/prisma.js';
import { BANK_COUNTRIES, COUNTRY_CURRENCY } from '../lib/domain.js';
import { RESPONSE_CODES } from '../lib/responseCodes.js';

export const metaRoutes: FastifyPluginAsyncTypebox = async (app) => {
  app.get('/health', {
    schema: { tags: ['Meta'], summary: 'Saúde da API e do banco de dados' },
    handler: async () => {
      await prisma.$queryRaw`SELECT 1`;
      return { status: 'ok' };
    },
  });

  app.get('/api/reference', {
    schema: { tags: ['Meta'], summary: 'Países atendidos, moedas e códigos de resposta das transações' },
    handler: () => ({
      countries: BANK_COUNTRIES.map((country) => ({ country, currency: COUNTRY_CURRENCY[country] })),
      response_codes: Object.entries(RESPONSE_CODES).map(([code, v]) => ({ code, ...v })),
    }),
  });
};
