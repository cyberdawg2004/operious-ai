/**
 * Frontend Result envelope.
 *
 * Mirrors the backend "never raises" discipline: SDK / fetch helpers return a
 * Result instead of throwing. UI components branch on `ok` and render the
 * appropriate inspectable surface (success vs error envelope).
 *
 * This is a frontend convention only. It has no operational authority — it
 * exists so the UI can deterministically render error envelopes without
 * exception-driven control flow.
 */

export interface OkResult<T> {
  readonly ok: true;
  readonly value: T;
}
export interface ErrResult<E> {
  readonly ok: false;
  readonly error: E;
}
export type Result<T, E = ResultError> = OkResult<T> | ErrResult<E>;

export interface ResultError {
  readonly code: string;
  readonly message: string;
  readonly substrate?: string;
  readonly correlationId?: string;
  readonly cause?: unknown;
}

export const ok = <T>(value: T): Result<T, never> => ({ ok: true, value });

export const err = <E extends ResultError>(error: E): Result<never, E> => ({
  ok: false,
  error,
});

export const isOk = <T, E>(result: Result<T, E>): result is OkResult<T> =>
  result.ok === true;

export const isErr = <T, E>(result: Result<T, E>): result is ErrResult<E> =>
  result.ok === false;
