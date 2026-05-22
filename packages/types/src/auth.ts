import type { PrincipalId, TenantId } from './ids';

/**
 * Mirror of the backend `MePrincipalResponse` returned by
 * `GET` against `ENDPOINT.auth.me`.
 *
 * The backend's `AuthorityContextMiddleware` is the sole authority over
 * principal identity. The frontend NEVER infers a principal from a JWT
 * directly — it always relies on the verified `/me` response.
 */

export type AuthoritySource = 'verified' | 'header' | 'anonymous';

export interface MePrincipalDto {
  readonly principalId?: PrincipalId;
  readonly tenantId?: TenantId;
  readonly organizationId?: string;
  readonly environmentId?: string;
  readonly capabilities: readonly string[];
  readonly authoritySource: AuthoritySource;
}
