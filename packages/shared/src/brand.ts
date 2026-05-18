/**
 * Branded type primitives.
 *
 * The frontend mirrors the backend's `NewType`-based identity discipline.
 * Every substrate identifier is a tagged string, never raw `string`. This
 * prevents accidental cross-substrate ID assignment at the type system level.
 */

declare const __operiousBrand: unique symbol;

export type Brand<T, B extends string> = T & { readonly [__operiousBrand]: B };

/** Coerce a raw string into a branded identifier. */
export const brand = <B extends string>(value: string): Brand<string, B> =>
  value as Brand<string, B>;

/** Strip the brand for serialization or comparison with raw strings. */
export const unbrand = <B extends string>(value: Brand<string, B>): string => value as string;
