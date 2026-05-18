'use client';

import { useMutation } from '@tanstack/react-query';
import { ENDPOINT } from '@operious/contracts';
import type {
  ClaimQueueItemMutation,
  ClaimQueueItemResult,
  RequestApprovalMutation,
  RequestApprovalResult,
} from '@operious/contracts';
import { isErr } from '@operious/shared';

import { useAuthedRequest } from './client';

/**
 * Mutation hooks.
 *
 * CRITICAL: optimistic updates are forbidden. Every mutation hook resolves
 * ONLY after the backend returns its envelope. The UI renders the resulting
 * envelope verbatim — `accepted: false` means the request was admitted but
 * the backend declined; `ok: false` means the transport itself failed.
 *
 * The frontend NEVER auto-retries a denied operational mutation.
 */

export const useRequestApproval = () => {
  const request = useAuthedRequest();
  return useMutation<RequestApprovalResult, Error, RequestApprovalMutation>({
    retry: false,
    mutationFn: async (input) => {
      const envelope = await request<RequestApprovalResult>(
        ENDPOINT.cognition.approvalRequest(input.proposalId as unknown as string),
        {
          method: 'POST',
          body: {
            approverId: input.approverId,
            justification: input.justification,
            clientCorrelationId: input.clientCorrelationId,
          },
        },
      );
      const result = envelope.result;
      if (isErr(result)) {
        throw new Error(result.error.message);
      }
      return result.value;
    },
  });
};

export const useClaimQueueItem = () => {
  const request = useAuthedRequest();
  return useMutation<ClaimQueueItemResult, Error, ClaimQueueItemMutation>({
    retry: false,
    mutationFn: async (input) => {
      const envelope = await request<ClaimQueueItemResult>(
        ENDPOINT.operations.queueItem(input.itemId as unknown as string),
        {
          method: 'POST',
          body: {
            principalId: input.principalId,
            clientCorrelationId: input.clientCorrelationId,
          },
        },
      );
      const result = envelope.result;
      if (isErr(result)) {
        throw new Error(result.error.message);
      }
      return result.value;
    },
  });
};
