export class AppError extends Error {
  constructor(
    public readonly statusCode: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
  }
}

export const notFound = (what: string, id: string) => new AppError(404, 'not_found', `${what} ${id} não encontrado(a).`);

export const unprocessable = (code: string, message: string, details?: unknown) =>
  new AppError(422, code, message, details);
