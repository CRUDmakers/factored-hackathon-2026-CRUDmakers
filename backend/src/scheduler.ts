import type { FastifyBaseLogger } from 'fastify';
import { runDueSchedules } from './services/scheduled.js';

/** Executa os agendamentos vencidos a cada `intervalMs`. Devolve a função que para o executor. */
export function startScheduler(intervalMs: number, log: FastifyBaseLogger): () => void {
  let running = false;
  const tick = async () => {
    if (running) return;
    running = true;
    try {
      const executed = await runDueSchedules();
      if (executed.length) log.info({ executed }, 'agendamentos executados');
    } catch (err) {
      log.error(err, 'falha ao executar agendamentos');
    } finally {
      running = false;
    }
  };
  const timer = setInterval(tick, intervalMs);
  return () => clearInterval(timer);
}
