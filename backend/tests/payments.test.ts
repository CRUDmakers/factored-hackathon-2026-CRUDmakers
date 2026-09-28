import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { prisma } from '../src/db/prisma.js';
import { ANA, BARCODE, BRUNO, CARLA, UNKNOWN, balanceOf, ownerApp, resetData } from './helpers.js';

let app: FastifyInstance;
beforeAll(async () => {
  app = await ownerApp();
});
beforeEach(resetData);
afterAll(() => app.close());

const post = (path: string, payload: object, customer = ANA) =>
  app.inject({ method: 'POST', url: `/api/customers/${customer}/${path}`, payload });

const CHK = 'PRD-ANACHK000001';

describe('transferências (feature 2)', () => {
  it('paga a fatura do próprio cartão: debita a conta e reduz a fatura', async () => {
    const res = await post('transfers', { source_product_id: CHK, amount: 100, to_product_id: 'PRD-ANACC0000003', description: 'fatura' });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body).toMatchObject({
      status: 'Approved',
      completed: true,
      response_code: '00',
      transaction_type: 'Payment',
      source: { debited_amount: 100, balance_after: 900 },
      credited: { product_id: 'PRD-ANACC0000003', amount: 100, currency: 'USD' },
      counterparty: { type: 'internal', own_product: true, recipient_name: 'Ana López', international: false },
      exchange: null,
      decline_detail: null,
    });
    expect(await balanceOf(CHK)).toBe(900);
    expect(await balanceOf('PRD-ANACC0000003')).toBe(100);

    const tx = (await app.inject(`/api/customers/${ANA}/transactions/${body.transaction_id}`)).json();
    expect(tx).toMatchObject({ origin: 'simulated', payment_method: 'transfer', description: 'fatura', balance_after: 900, related_product_id: 'PRD-ANACC0000003' });
    const credit = await prisma.transaction.findUniqueOrThrow({ where: { transaction_id: body.credited.transaction_id } });
    expect(credit).toMatchObject({ transaction_type: 'Deposit', description: `Pagamento recebido de ${CHK}` });
    expect(credit.amount_usd).toBeNull();
  });

  it('transfere para outro cliente em outro país, convertendo a moeda', async () => {
    const body = (await post('transfers', { source_product_id: CHK, amount: 50, to_product_id: 'PRD-BRUCHK000001' })).json();
    expect(body).toMatchObject({
      transaction_type: 'Transfer',
      counterparty: { own_product: false, recipient_name: 'Bruno Gómez', international: true },
      credited: { amount: 200000, currency: 'COP' },
    });
    expect(body.counterparty.destination_amount).toBeUndefined();
    expect(await balanceOf('PRD-BRUCHK000001')).toBe(2200000);
    const credit = await prisma.transaction.findUniqueOrThrow({ where: { transaction_id: body.credited.transaction_id } });
    expect(credit).toMatchObject({ customer_id: BRUNO, transaction_country: 'Colombia', description: `Recebido de ${CHK}` });
    expect(credit.amount_usd?.toNumber()).toBe(50);
  });

  it('transfere de pessoa para pessoa pelo número da conta', async () => {
    const body = (await post('transfers', { source_product_id: CHK, amount: 50, to_account_number: '5000-000 001' })).json();
    expect(body).toMatchObject({
      completed: true,
      transaction_type: 'Transfer',
      counterparty: { type: 'internal', to_product_id: 'PRD-BRUCHK000001', to_account_number: '5000000001', recipient_name: 'Bruno Gómez', own_product: false },
      credited: { amount: 200000, currency: 'COP' },
    });
    expect(await balanceOf('PRD-BRUCHK000001')).toBe(2200000);
  });

  it.each([
    ['conta inexistente', '999', 'Conta de destino não encontrada.'],
    ['número repetido no dataset', '1234567890123456', 'Número de conta ambíguo: mais de uma conta com esse número.'],
    ['conta suspensa', '5000000002', 'A conta de destino está com status Suspended.'],
  ])('recusa pelo número da conta: %s', async (_, number, detail) => {
    const body = (await post('transfers', { source_product_id: CHK, amount: 10, to_account_number: number })).json();
    expect(body).toMatchObject({ status: 'Declined', response_code: '14', decline_detail: detail });
    expect(await balanceOf(CHK)).toBe(1000);
  });

  it('número da conta não aponta para investimento nem para a própria conta de origem', async () => {
    const investment = await post('transfers', { source_product_id: CHK, amount: 10, to_account_number: '6000000002' });
    expect(investment.json()).toMatchObject({ status: 'Declined', decline_detail: 'Conta de destino não encontrada.' });
    const self = await post('transfers', { source_product_id: CHK, amount: 10, to_account_number: '4000000001' });
    expect(self.statusCode).toBe(422);
    expect(self.json().message).toBe('O produto de origem e o de destino são iguais.');
  });

  it('paga cartão sem número registrado pelo ID do produto', async () => {
    const body = (await post('transfers', { source_product_id: CHK, amount: 10, to_product_id: 'PRD-ANACCZERO010' })).json();
    expect(body).toMatchObject({ completed: true, counterparty: { to_account_number: null } });
    expect(await balanceOf('PRD-ANACCZERO010')).toBe(-10);
  });

  it('transfere para produto sem dono conhecido e sem saldo registrado', async () => {
    const body = (await post('transfers', { source_product_id: CHK, amount: 10, to_product_id: 'PRD-ORPHAN000001' })).json();
    expect(body).toMatchObject({ completed: true, counterparty: { recipient_name: null, international: false } });
    expect(await balanceOf('PRD-ORPHAN000001')).toBe(10);
  });

  it('valor em outra moeda é convertido para a moeda da conta', async () => {
    const body = (
      await post('transfers', {
        source_product_id: CHK,
        amount: 180,
        currency: 'MXN',
        beneficiary: { name: 'Luis', account_number: '123', country: 'Mexico' },
      })
    ).json();
    expect(body).toMatchObject({ currency: 'MXN', source: { debited_amount: 10, balance_after: 990 }, exchange: { from: 'MXN', to: 'USD' } });
    expect(body.counterparty).toMatchObject({ type: 'external', country: 'México', bank_name: null, document_number: null, international: false });
    const tx = await prisma.transaction.findUniqueOrThrow({ where: { transaction_id: body.transaction_id } });
    expect(tx.amount_usd?.toNumber()).toBe(10);
  });

  it('envio para outro banco em outro país mostra quanto chega na moeda local', async () => {
    const body = (
      await post('transfers', {
        source_product_id: CHK,
        amount: 100,
        beneficiary: { name: 'Sofía', account_number: '999', bank_name: 'Bancolombia', country: 'Colombia', document_number: '42' },
      })
    ).json();
    expect(body.counterparty).toMatchObject({
      international: true,
      bank_name: 'Bancolombia',
      destination_amount: { currency: 'COP', amount: 400000, rate: 4000, rate_date: '2026-06-17' },
    });
  });

  it('país onde o banco não opera é recusado com 422', async () => {
    const res = await post('transfers', { source_product_id: CHK, amount: 10, beneficiary: { name: 'X', account_number: '1', country: 'USA' } });
    expect(res.statusCode).toBe(422);
    expect(res.json()).toMatchObject({ error: 'country_not_supported', details: { supported_countries: ['México', 'Colombia', 'Argentina'] } });
  });

  it.each([
    ['sem destino', {}],
    ['com dois destinos', { to_product_id: 'PRD-BRUCHK000001', beneficiary: { name: 'X', account_number: '1', country: 'MX' } }],
    ['com conta e produto', { to_product_id: 'PRD-BRUCHK000001', to_account_number: '5000000001' }],
    ['para o mesmo produto', { to_product_id: CHK }],
    ['para investimento', { to_product_id: 'PRD-CARINV000002' }],
  ])('destino inválido (%s) retorna 422 sem gravar', async (_, destination) => {
    const res = await post('transfers', { source_product_id: CHK, amount: 10, ...destination });
    expect(res.statusCode).toBe(422);
    expect(res.json().error).toBe('invalid_destination');
    expect(await prisma.transaction.count({ where: { origin: 'simulated' } })).toBe(0);
  });

  it('cartão de crédito não pode ser origem de transferência', async () => {
    const res = await post('transfers', { source_product_id: 'PRD-ANACC0000003', amount: 10, to_product_id: 'PRD-BRUCHK000001' });
    expect(res.statusCode).toBe(422);
    expect(res.json()).toMatchObject({ error: 'invalid_source_product', details: { allowed_product_types: expect.any(Array) } });
  });

  it('404 para produto de origem inexistente ou de outro cliente', async () => {
    expect((await post('transfers', { source_product_id: 'PRD-NOPE', amount: 1, to_product_id: CHK })).statusCode).toBe(404);
    expect((await post('transfers', { source_product_id: CHK, amount: 1, to_product_id: 'PRD-BRUCHK000001' }, UNKNOWN)).statusCode).toBe(404);
  });

  it('400 para valor não positivo', async () => {
    expect((await post('transfers', { source_product_id: CHK, amount: 0, to_product_id: 'PRD-BRUCHK000001' })).statusCode).toBe(400);
  });

  it.each([
    ['saldo insuficiente', CHK, 'PRD-BRUCHK000001', '51', 'Saldo disponível (1000.00 USD) insuficiente.'],
    ['produto bloqueado', 'PRD-ANADEB000005', 'PRD-BRUCHK000001', '05', 'O produto de origem está com status Blocked.'],
    ['cartão vencido', 'PRD-ANADEBEXP012', 'PRD-BRUCHK000001', '54', 'O cartão venceu em 2024-01-01.'],
    ['destino inexistente', CHK, 'PRD-NAOEXISTE01', '14', 'Conta de destino não encontrada.'],
    ['destino suspenso', CHK, 'PRD-BRUSAV000002', '14', 'A conta de destino está com status Suspended.'],
  ])('recusa por %s: grava como Declined e não move saldo', async (_, source, dest, code, detail) => {
    const amount = code === '51' ? 5000 : 10;
    const res = await post('transfers', { source_product_id: source, amount, to_product_id: dest });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body).toMatchObject({ status: 'Declined', completed: false, response_code: code, decline_detail: detail, credited: null });
    expect(body.source.debited_amount).toBe(0);
    expect(await balanceOf(CHK)).toBe(1000);

    const status = (await app.inject(`/api/customers/${ANA}/transactions/${body.transaction_id}/status`)).json();
    expect(status).toMatchObject({ status: 'Declined', response_code: code });
  });

  it('dry_run simula sem gravar nem mover saldo', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/customers/${ANA}/transfers?dry_run=true`,
      payload: { source_product_id: CHK, amount: 100, to_product_id: 'PRD-BRUCHK000001' },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ preview: true, transaction_id: null, credited: null, completed: true, source: { balance_after: 900 } });
    expect(await balanceOf(CHK)).toBe(1000);
    expect(await prisma.transaction.count({ where: { origin: 'simulated' } })).toBe(0);
  });
});

describe('Pix (feature 2)', () => {
  it.each([
    ['e-mail (sem diferenciar maiúsculas)', 'BRUNO@test.com'],
    ['celular com formatação', '+57 (300) 111-2222'],
    ['documento', 'DOC-BRUNO'],
  ])('encontra o destinatário por %s', async (_, key) => {
    const res = await post('pix', { source_product_id: CHK, amount: 25, pix_key: key });
    expect(res.statusCode).toBe(201);
    expect(res.json()).toMatchObject({
      method: 'pix',
      completed: true,
      counterparty: { type: 'pix', recipient_name: 'Bruno Gómez', recipient_product_id: 'PRD-BRUCHK000001', international: true },
      credited: { amount: 100000, currency: 'COP' },
    });
  });

  it.each([
    ['chave inexistente', 'ninguem@test.com'],
    ['cliente sem conta ativa', 'carla@test.com'],
    ['número curto demais para ser celular', '1234'],
  ])('recusa com 14 quando a chave não resolve (%s)', async (_, key) => {
    const body = (await post('pix', { source_product_id: CHK, amount: 25, pix_key: key })).json();
    expect(body).toMatchObject({ status: 'Declined', response_code: '14', reason_code: 'invalid_account' });
    expect(await balanceOf(CHK)).toBe(1000);
  });

  it('chave em branco retorna 422', async () => {
    const res = await post('pix', { source_product_id: CHK, amount: 25, pix_key: '   ' });
    expect(res.statusCode).toBe(422);
  });

  it('dry_run de Pix', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/customers/${CARLA}/pix?dry_run=true`,
      payload: { source_product_id: 'PRD-CARCHK000001', amount: 1, pix_key: 'ana@test.com' },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ preview: true, response_code: '05' });
  });
});

describe('pagamento de boletos (feature 2)', () => {
  it('paga com cartão de crédito: usa o limite e aumenta a fatura', async () => {
    const res = await post('bill-payments', {
      source_product_id: 'PRD-ANACC0000003',
      amount: 150,
      barcode: '2379.33812 86000.000000 00000.000000 0 00000000000000',
      biller_name: 'CFE Luz',
      due_date: '2020-01-10',
      category: 'Utilities',
    });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body).toMatchObject({
      transaction_type: 'Payment',
      completed: true,
      source: { balance_after: 350 },
      counterparty: { type: 'bill', biller_name: 'CFE Luz', paid_after_due_date: true, barcode: expect.stringMatching(/^2379338128600000\d{30}$/) },
    });
    const tx = await prisma.transaction.findUniqueOrThrow({ where: { transaction_id: body.transaction_id } });
    expect(tx).toMatchObject({ transaction_category: 'Utilities', merchant_name: 'CFE Luz', transaction_city: 'Ciudad de México' });
  });

  it('sem campos opcionais usa a categoria Services', async () => {
    const body = (await post('bill-payments', { source_product_id: CHK, amount: 10, barcode: BARCODE })).json();
    expect(body.counterparty).toMatchObject({ biller_name: null, due_date: null, paid_after_due_date: false });
    const tx = await prisma.transaction.findUniqueOrThrow({ where: { transaction_id: body.transaction_id } });
    expect(tx).toMatchObject({ transaction_category: 'Services', merchant_name: null });
  });

  it('vencimento futuro não é pago em atraso', async () => {
    const body = (await post('bill-payments', { source_product_id: CHK, amount: 10, barcode: BARCODE, due_date: '2099-12-31' })).json();
    expect(body.counterparty.paid_after_due_date).toBe(false);
  });

  it.each([
    ['cartão vencido', 'PRD-ANACCEXP0004', '54'],
    ['cartão sem limite', 'PRD-ANACCZERO010', '51'],
  ])('recusa por %s', async (_, source, code) => {
    const body = (await post('bill-payments', { source_product_id: source, amount: 10, barcode: BARCODE })).json();
    expect(body).toMatchObject({ status: 'Declined', response_code: code });
  });

  it('limite insuficiente descreve o limite disponível', async () => {
    const body = (await post('bill-payments', { source_product_id: 'PRD-ANACC0000003', amount: 900, barcode: BARCODE })).json();
    expect(body.decline_detail).toBe('Limite disponível (800.00 USD) insuficiente.');
  });

  it.each([['123'], ['1'.repeat(49)]])('código de barras inválido retorna 422 (%s)', async (barcode) => {
    const res = await post('bill-payments', { source_product_id: CHK, amount: 10, barcode });
    expect(res.statusCode).toBe(422);
    expect(res.json().error).toBe('invalid_barcode');
  });

  it('dry_run também valida e devolve o erro', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/customers/${ANA}/bill-payments?dry_run=true`,
      payload: { source_product_id: CHK, amount: 10, barcode: '1' },
    });
    expect(res.statusCode).toBe(422);
  });
});
