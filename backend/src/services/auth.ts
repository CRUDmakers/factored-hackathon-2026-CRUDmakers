/**
 * Provedor de identidade de TESTE (simulação para o hackathon, não é login real).
 * Quem tem a chave de serviço (o frontend/demo, no papel do provedor confiável) pede
 * uma sessão para um cliente; a API emite um JWT HS256 curto com sub = customer_id.
 */
import { createHash, randomUUID, timingSafeEqual } from 'node:crypto';
import { TokenError, createSigner, createVerifier } from 'fast-jwt';
import { config } from '../config.js';
import { prisma } from '../db/prisma.js';
import { AppError, notFound } from '../lib/errors.js';

export const TOKEN_ISSUER = 'banking-cs-test-idp';
export const SERVICE_KEY_HEADER = 'x-service-key';

export interface Session {
  sub: string;
  jti: string;
  exp: number;
}

export const unauthorized = (message: string) => new AppError(401, 'unauthorized', message);

/** Assina um token de sessão. `now` só muda nos testes (para gerar tokens já expirados). */
export function signSession(customerId: string, now = Date.now()) {
  const jti = randomUUID();
  const ttl = config.authSessionTtlSeconds;
  const sign = createSigner({
    key: config.authJwtSecret,
    algorithm: 'HS256',
    expiresIn: ttl * 1000,
    iss: TOKEN_ISSUER,
    sub: customerId,
    jti,
    clockTimestamp: now,
  });
  return { token: sign({}), jti, expiresAt: new Date((Math.floor(now / 1000) + ttl) * 1000) };
}

function verifySession(token: string): Session {
  const verify = createVerifier({
    key: config.authJwtSecret,
    algorithms: ['HS256'],
    allowedIss: TOKEN_ISSUER,
    requiredClaims: ['sub', 'jti', 'exp'],
  });
  try {
    return verify(token) as Session;
  } catch (err) {
    if ((err as TokenError).code === TokenError.codes.expired) {
      throw new AppError(401, 'session_expired', 'Sessão expirada. Inicie uma nova sessão.');
    }
    throw unauthorized('Token de sessão inválido.');
  }
}

/** Valida o header `Authorization: Bearer <token>` e confere se a sessão não foi encerrada. */
export async function authenticate(authorization: string | undefined): Promise<Session> {
  const token = /^Bearer\s+(\S+)$/i.exec(authorization ?? '')?.[1];
  if (!token) throw unauthorized('Envie o header Authorization: Bearer <token>.');
  const session = verifySession(token);
  if (await prisma.revokedSession.count({ where: { jti: session.jti } })) {
    throw new AppError(401, 'session_revoked', 'Sessão encerrada. Inicie uma nova sessão.');
  }
  return session;
}

const digest = (value: string) => createHash('sha256').update(value).digest();

/** Compara a chave de serviço em tempo constante. */
export function assertServiceKey(value: unknown): void {
  if (typeof value !== 'string' || !timingSafeEqual(digest(value), digest(config.authServiceKey))) {
    throw unauthorized('Chave de serviço ausente ou inválida.');
  }
}

export async function issueTestSession(customerId: string) {
  const customer = await prisma.customer.findUnique({ where: { customer_id: customerId }, select: { customer_status: true } });
  if (!customer) throw notFound('Cliente', customerId);
  if (customer.customer_status !== 'Active') {
    throw new AppError(403, 'customer_inactive', `Cliente ${customerId} não está ativo (status: ${customer.customer_status}).`);
  }
  const { token, jti, expiresAt } = signSession(customerId);
  return {
    access_token: token,
    token_type: 'Bearer',
    expires_in: config.authSessionTtlSeconds,
    expires_at: expiresAt,
    session_id: jti,
    customer_id: customerId,
  };
}

export function describeSession(session: Session) {
  return { customer_id: session.sub, session_id: session.jti, expires_at: new Date(session.exp * 1000) };
}

/** Logout: guarda o jti até o token expirar e aproveita para limpar os que já expiraram. */
export async function revokeSession(session: Session): Promise<void> {
  await prisma.$transaction([
    prisma.revokedSession.deleteMany({ where: { expires_at: { lt: new Date() } } }),
    prisma.revokedSession.createMany({
      data: [{ jti: session.jti, customer_id: session.sub, expires_at: new Date(session.exp * 1000) }],
      skipDuplicates: true,
    }),
  ]);
}
