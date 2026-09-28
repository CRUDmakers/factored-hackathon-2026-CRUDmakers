/** Códigos ISO 8583 presentes em transactions.response_code. */
export const RESPONSE_CODES = {
  '00': { reason_code: 'approved', description: 'Transação aprovada.' },
  '05': {
    reason_code: 'do_not_honor',
    description: 'Transação não autorizada pelo banco (produto bloqueado/inativo ou regra de segurança).',
  },
  '14': { reason_code: 'invalid_account', description: 'Conta, cartão ou destinatário inválido.' },
  '51': { reason_code: 'insufficient_funds', description: 'Saldo ou limite insuficiente.' },
  '54': { reason_code: 'expired_card', description: 'Cartão ou produto vencido.' },
} as const;

export type ResponseCode = keyof typeof RESPONSE_CODES;

const STATUS_DESCRIPTIONS: Record<string, string> = {
  Approved: 'Concluída com sucesso.',
  Declined: 'Negada.',
  Pending: 'Em processamento, ainda não concluída.',
  Reversed: 'Estornada: o valor foi devolvido.',
};

export interface StatusExplanation {
  status: string;
  status_description: string;
  completed: boolean;
  response_code: string | null;
  reason_code: string | null;
  reason: string | null;
}

export function explainStatus(status: string | null, responseCode: string | null): StatusExplanation {
  const approved = status === 'Approved';
  const known = !approved && responseCode && responseCode !== '00'
    ? RESPONSE_CODES[responseCode as ResponseCode]
    : undefined;
  const failed = status === 'Declined' || status === 'Reversed';
  return {
    status: status ?? 'Unknown',
    status_description: STATUS_DESCRIPTIONS[status ?? ''] ?? 'Status desconhecido.',
    completed: approved,
    response_code: responseCode,
    reason_code: known?.reason_code ?? null,
    reason: known?.description ?? (failed ? 'O motivo não foi registrado.' : null),
  };
}
