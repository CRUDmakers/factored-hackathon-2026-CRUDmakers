import { afterAll } from 'vitest';
import { disconnect } from '../src/db/prisma.js';

// Cada arquivo de teste importa os módulos de novo (isolate), então fecha o próprio pool.
afterAll(disconnect);
