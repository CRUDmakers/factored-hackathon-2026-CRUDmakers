import { buildApp } from './app.js';
import { config } from './config.js';
import { startScheduler } from './scheduler.js';

export async function start(opts: { port?: number; host?: string; schedulerIntervalMs?: number } = {}) {
  const app = await buildApp({ logger: { level: config.logLevel } });
  await app.listen({ port: opts.port ?? config.port, host: opts.host ?? config.host });
  const stopScheduler = startScheduler(opts.schedulerIntervalMs ?? config.schedulerIntervalMs, app.log);

  return {
    app,
    async stop() {
      stopScheduler();
      await app.close();
    },
  };
}
