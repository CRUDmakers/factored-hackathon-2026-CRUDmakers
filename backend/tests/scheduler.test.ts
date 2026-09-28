import type { FastifyBaseLogger } from 'fastify';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { runDueSchedules } = vi.hoisted(() => ({ runDueSchedules: vi.fn() }));
vi.mock('../src/services/scheduled.js', () => ({ runDueSchedules }));

const { startScheduler } = await import('../src/scheduler.js');

const log = { info: vi.fn(), error: vi.fn() } as unknown as FastifyBaseLogger;

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
});
afterEach(() => vi.useRealTimers());

describe('startScheduler', () => {
  it('executa a cada intervalo e registra o que rodou', async () => {
    runDueSchedules.mockResolvedValueOnce([]).mockResolvedValueOnce([{ scheduled_payment_id: 'SCH-1' }]);
    const stop = startScheduler(1000, log);

    await vi.advanceTimersByTimeAsync(1000);
    expect(log.info).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1000);
    expect(log.info).toHaveBeenCalledWith({ executed: [{ scheduled_payment_id: 'SCH-1' }] }, 'agendamentos executados');

    stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(runDueSchedules).toHaveBeenCalledTimes(2);
  });

  it('não sobrepõe execuções e continua após erro', async () => {
    let finish!: () => void;
    runDueSchedules
      .mockReturnValueOnce(new Promise((resolve) => (finish = () => resolve([]))))
      .mockRejectedValueOnce(new Error('db fora'));
    const stop = startScheduler(1000, log);

    await vi.advanceTimersByTimeAsync(3000); // 3 ticks, mas a primeira execução ainda não terminou
    expect(runDueSchedules).toHaveBeenCalledTimes(1);

    finish();
    await vi.advanceTimersByTimeAsync(1000);
    expect(runDueSchedules).toHaveBeenCalledTimes(2);
    expect(log.error).toHaveBeenCalledWith(expect.any(Error), 'falha ao executar agendamentos');
    stop();
  });
});
