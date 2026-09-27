// Ponto de entrada do processo (fora da cobertura: só liga o servidor e trata sinais).
import { disconnect } from './db/prisma.js';
import { start } from './server.js';

const server = await start();
for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.once(signal, async () => {
    await server.stop();
    await disconnect();
  });
}
