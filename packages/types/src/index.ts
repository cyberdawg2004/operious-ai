/**
 * @operious/types
 *
 * Frontend DTO mirrors of the backend substrate contracts.
 *
 * THIS PACKAGE IS THE SINGLE SOURCE OF TRUTH for shapes the frontend renders.
 * It MUST NEVER:
 *   - introduce schemas the backend does not own
 *   - add operational semantics the backend does not encode
 *   - duplicate enum values out of sync with the backend `app/<substrate>/enums.py` files
 *
 * Wire-format discipline: all enums below are pinned to backend wire values.
 * If the backend changes a value, this package MUST change too — and that is
 * intentionally a breaking change at type-check time across both apps.
 */

export * from './ids';
export * from './common';
export * from './session';
export * from './governance';
export * from './arbitration';
export * from './boundary';
export * from './translation';
export * from './voice';
export * from './topology';
export * from './intelligence';
export * from './operations';
export * from './trace';
