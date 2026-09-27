import { afterEach, describe, expect, it, vi } from 'vitest';

const KEYS = ['HOST', 'PORT', 'DATABASE_URL', 'DATA_DIR', 'SCHEDULER_INTERVAL_MS', 'LOG_LEVEL'] as const;
const original = Object.fromEntries(KEYS.map((k) => [k, process.env[k]]));

async function freshConfig() {
  vi.resetModules();
  return (await import('../src/config.js')).config;
}

afterEach(() => {
  for (const k of KEYS) {
    if (original[k] === undefined) delete process.env[k];
    else process.env[k] = original[k];
  }
});

describe('config', () => {
  it('lê as variáveis de ambiente', async () => {
    Object.assign(process.env, {
      HOST: '127.0.0.1',
      PORT: '8080',
      DATABASE_URL: 'postgresql://u:p@h:1/db',
      DATA_DIR: '/data',
      SCHEDULER_INTERVAL_MS: '5000',
      LOG_LEVEL: 'debug',
    });
    expect(await freshConfig()).toEqual({
      host: '127.0.0.1',
      port: 8080,
      databaseUrl: 'postgresql://u:p@h:1/db',
      dataDir: '/data',
      schedulerIntervalMs: 5000,
      logLevel: 'debug',
    });
  });

  it('usa valores padrão', async () => {
    for (const k of KEYS) delete process.env[k];
    expect(await freshConfig()).toEqual({
      host: '0.0.0.0',
      port: 3000,
      databaseUrl: 'postgresql://banking:banking@localhost:5432/banking',
      dataDir: '../data',
      schedulerIntervalMs: 60_000,
      logLevel: 'info',
    });
  });
});
