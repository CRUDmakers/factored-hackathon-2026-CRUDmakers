export const config = {
  host: process.env.HOST ?? '0.0.0.0',
  port: Number(process.env.PORT ?? 3000),
  databaseUrl: process.env.DATABASE_URL ?? 'postgresql://banking:banking@localhost:5432/banking',
  dataDir: process.env.DATA_DIR ?? '../data',
  schedulerIntervalMs: Number(process.env.SCHEDULER_INTERVAL_MS ?? 60_000),
  logLevel: process.env.LOG_LEVEL ?? 'info',
};
