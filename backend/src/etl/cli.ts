// Uso: node dist/etl/cli.js [--force]
import { config } from '../config.js';
import { disconnect } from '../db/prisma.js';
import { loadData } from './load.js';

loadData({ dataDir: config.dataDir, force: process.argv.includes('--force') })
  .catch((err) => {
    console.error(err);
    process.exitCode = 1;
  })
  .finally(disconnect);
