import { beforeAll, describe, expect, it } from 'vitest';
import { Decimal } from '../src/db/prisma.js';
import type { Product } from '../src/generated/prisma/client.js';
import { presentProduct } from '../src/services/customers.js';
import { getRate } from '../src/services/exchange.js';
import { createSchedule } from '../src/services/scheduled.js';
import { ANA, resetData } from './helpers.js';

beforeAll(resetData);

describe('casos de borda dos serviços', () => {
  it('cotação inexistente sem data informada', async () => {
    await expect(getRate('usd', 'eur')).rejects.toMatchObject({
      statusCode: 404,
      message: 'Não há cotação de USD para EUR.',
    });
  });

  it('cartão com limite e saldo não registrado tem todo o limite disponível', () => {
    const product = {
      product_id: 'PRD-X',
      product_type: 'Tarjeta Crédito',
      product_number: null,
      currency: 'USD',
      current_balance: null,
      credit_limit: new Decimal(750),
      expiration_date: null,
      opening_date: null,
    } as unknown as Product;
    expect(presentProduct(product).available_credit?.toNumber()).toBe(750);
  });

  it('boleto agendado sem código de barras é rejeitado', async () => {
    await expect(
      createSchedule(ANA, {
        source_product_id: 'PRD-ANACHK000001',
        method: 'bill_payment',
        amount: 10,
        destination: {},
        frequency: 'once',
      }),
    ).rejects.toMatchObject({ statusCode: 422, code: 'invalid_barcode' });
  });
});
