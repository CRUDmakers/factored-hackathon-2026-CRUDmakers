import { describe, expect, it } from 'vitest';
import { displayNumber, isoDay, maskNumber, round2, toBankCountry } from '../src/lib/domain.js';
import { AppError, notFound, unprocessable } from '../src/lib/errors.js';
import { newId } from '../src/lib/ids.js';
import { explainStatus } from '../src/lib/responseCodes.js';
import { nextRun } from '../src/services/scheduled.js';
import { describeLocation, explainAdjustment } from '../src/services/transactions.js';

describe('domain', () => {
  it('normaliza países do banco com e sem acento, siglas e caixa', () => {
    expect(toBankCountry('Mexico')).toBe('México');
    expect(toBankCountry(' méxico ')).toBe('México');
    expect(toBankCountry('CO')).toBe('Colombia');
    expect(toBankCountry('argentina')).toBe('Argentina');
    expect(toBankCountry('USA')).toBeNull();
    expect(toBankCountry(null)).toBeNull();
    expect(toBankCountry(undefined)).toBeNull();
  });

  it('formata valores', () => {
    expect(round2(1.005)).toBe(1.01);
    expect(maskNumber('4332181960')).toBe('•••• 1960');
    expect(maskNumber(null)).toBeNull();
    expect(displayNumber('Tarjeta Crédito', '4672423884969653')).toBe('•••• 9653');
    expect(displayNumber('Cuenta Corriente', '4332181960')).toBe('4332181960');
    expect(isoDay(new Date('2025-08-11T00:00:00Z'))).toBe('2025-08-11');
    expect(isoDay(null)).toBeNull();
  });
});

describe('errors e ids', () => {
  it('cria erros com status e código', () => {
    expect(notFound('Cliente', 'X')).toMatchObject({ statusCode: 404, code: 'not_found' });
    const err = unprocessable('bad', 'msg', { a: 1 });
    expect(err).toBeInstanceOf(AppError);
    expect(err).toMatchObject({ statusCode: 422, code: 'bad', message: 'msg', details: { a: 1 } });
  });

  it('gera IDs no formato do dataset', () => {
    expect(newId('TRX', 20)).toMatch(/^TRX-[A-Z0-9]{20}$/);
  });
});

describe('explainStatus', () => {
  it('aprovada não tem motivo', () => {
    expect(explainStatus('Approved', '00')).toMatchObject({ completed: true, reason: null, reason_code: null });
  });

  it('negada com código conhecido explica o motivo', () => {
    expect(explainStatus('Declined', '51')).toMatchObject({
      completed: false,
      reason_code: 'insufficient_funds',
      reason: 'Saldo ou limite insuficiente.',
    });
  });

  it('negada/estornada sem código informa que o motivo não foi registrado', () => {
    expect(explainStatus('Reversed', null).reason).toBe('O motivo não foi registrado.');
    expect(explainStatus('Declined', '00').reason).toBe('O motivo não foi registrado.');
  });

  it('pendente com código mostra o motivo; sem código, nenhum', () => {
    expect(explainStatus('Pending', '05').reason_code).toBe('do_not_honor');
    expect(explainStatus('Pending', null).reason).toBeNull();
  });

  it('status desconhecido', () => {
    expect(explainStatus(null, null)).toMatchObject({ status: 'Unknown', status_description: 'Status desconhecido.' });
  });
});

describe('nextRun', () => {
  const base = new Date('2026-01-31T12:00:00Z');
  it('calcula a próxima execução para cada frequência', () => {
    expect(nextRun(base, 'once')).toBeNull();
    expect(nextRun(base, 'daily')?.toISOString()).toBe('2026-02-01T12:00:00.000Z');
    expect(nextRun(base, 'weekly')?.toISOString()).toBe('2026-02-07T12:00:00.000Z');
  });

  it('mensal mantém o dia ou usa o último dia do mês', () => {
    expect(nextRun(base, 'monthly')?.toISOString()).toBe('2026-02-28T12:00:00.000Z');
    expect(nextRun(new Date('2026-03-15T00:00:00Z'), 'monthly')?.toISOString()).toBe('2026-04-15T00:00:00.000Z');
  });
});

describe('describeLocation', () => {
  const branch = { branch_name: 'Centro', address: 'Rua 1', city: 'CDMX' };
  it('descreve canais físicos com e sem agência', () => {
    expect(describeLocation({ channel: 'ATM', merchant: null, city: null, branch })).toBe(
      'Caixa eletrônico (ATM): agência Centro — Rua 1, CDMX',
    );
    expect(describeLocation({ channel: 'POS', merchant: 'Loja', city: 'Bogotá', branch: null })).toBe('Maquininha (POS) em Loja: Bogotá');
    expect(describeLocation({ channel: 'Branch', merchant: null, city: null, branch: null })).toBe('Guichê de agência: local não informado');
  });

  it('descreve canais digitais', () => {
    expect(describeLocation({ channel: 'App', merchant: null, city: null, branch: null })).toBe('Canal digital (App)');
    expect(describeLocation({ channel: null, merchant: null, city: null, branch: null })).toBe('Canal digital (não informado)');
  });
});

describe('explainAdjustment', () => {
  it('explica ajustes por tipo de produto', () => {
    expect(explainAdjustment('Préstamo Personal', 10)).toContain('10 dia(s) de atraso');
    expect(explainAdjustment('Préstamo Hipotecario', 0)).not.toContain('atraso');
    expect(explainAdjustment('Préstamo Hipotecario', null)).not.toContain('atraso');
    expect(explainAdjustment('Inversión', null)).toContain('investimento');
    expect(explainAdjustment('Seguro', null)).toContain('seguro');
    expect(explainAdjustment('Cuenta Corriente', null)).toBe('Ajuste lançado no produto Cuenta Corriente.');
  });
});
