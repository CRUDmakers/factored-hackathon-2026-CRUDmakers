import { existsSync } from 'node:fs';
import { defineConfig } from 'prisma/config';

// O CLI do Prisma não lê o .env sozinho. Variáveis já definidas no ambiente têm prioridade.
if (existsSync('.env')) process.loadEnvFile('.env');

export default defineConfig({
  schema: 'prisma/schema.prisma',
  migrations: {
    path: 'prisma/migrations',
  },
  datasource: {
    url: process.env.DATABASE_URL ?? 'postgresql://banking:banking@localhost:5432/banking',
  },
});
