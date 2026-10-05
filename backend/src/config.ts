// Segredos de autenticação só têm valor padrão fora de produção; em produção o buildApp recusa subir sem eles.
const dev = process.env.NODE_ENV !== 'production';

export const config = {
  host: process.env.HOST ?? '0.0.0.0',
  port: Number(process.env.PORT ?? 3000),
  databaseUrl: process.env.DATABASE_URL ?? 'postgresql://banking:banking@localhost:5432/banking',
  dataDir: process.env.DATA_DIR ?? '../data',
  schedulerIntervalMs: Number(process.env.SCHEDULER_INTERVAL_MS ?? 60_000),
  logLevel: process.env.LOG_LEVEL ?? 'info',
  authJwtSecret: process.env.AUTH_JWT_SECRET ?? (dev ? 'dev-only-jwt-secret-troque-em-producao' : ''),
  authServiceKey: process.env.AUTH_SERVICE_KEY ?? (dev ? 'dev-service-key' : ''),
  authSessionTtlSeconds: Number(process.env.AUTH_SESSION_TTL_SECONDS ?? 900),
  // Clientes que podem receber sessão de teste (IDs separados por vírgula). Vazio = todos (dev e testes).
  // Na demo pública a chave de serviço vai no bundle do frontend, então só os clientes da demo entram.
  authAllowedCustomers: (process.env.AUTH_ALLOWED_CUSTOMERS ?? '').split(',').map((id) => id.trim()).filter(Boolean),
};
