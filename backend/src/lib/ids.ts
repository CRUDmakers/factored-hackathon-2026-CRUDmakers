import { randomInt } from 'node:crypto';

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';

/** Gera IDs no mesmo formato do dataset, ex.: TRX-7I07NJ7LT0TPC5YC33UL. */
export function newId(prefix: string, length: number): string {
  let id = '';
  for (let i = 0; i < length; i++) id += ALPHABET[randomInt(ALPHABET.length)];
  return `${prefix}-${id}`;
}
