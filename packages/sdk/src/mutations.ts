'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ENDPOINT } from '@operious/contracts';
import type {
  ClaimQueueItemMutation,
  ClaimQueueItemResult,
  CreateChannelMutation,
  CreateChannelResult,
  CreateKnowledgeDocumentMutation,
  CreateKnowledgeDocumentResult,
  CreatePolicyMutation,
  CreatePolicyResult,
  RequestApprovalMutation,
  RequestApprovalResult,
  UpdateChannelMutation,
  UpdateChannelResult,
  UpdateKnowledgeDocumentMutation,
  UpdateKnowledgeDocumentResult,
  UpdatePolicyMutation,
  UpdatePolicyResult,
  VerifyChannelMutation,
  VerifyChannelResult,
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

// ---------------------------------------------------------------------------
// Tenant configuration mutations
//
// Every mutation invalidates the corresponding read key on success so that
// the UI re-fetches the canonical backend record. The frontend NEVER mutates
// cache contents directly with optimistic data.
// ---------------------------------------------------------------------------

export const useCreateChannel = () => {
  const request = useAuthedRequest();
  const queryClient = useQueryClient();
  return useMutation<CreateChannelResult, Error, CreateChannelMutation>({
    retry: false,
    mutationFn: async (input) => {
      const envelope = await request<CreateChannelResult>(
        ENDPOINT.tenant.channels,
        {
          method: 'POST',
          body: {
            channel_type: input.channelType,
            routing_address: input.routingAddress,
            credentials: input.credentials,
            webhook_secret: input.webhookSecret,
            status: input.status,
          },
        },
      );
      const result = envelope.result;
      if (isErr(result)) throw new Error(result.error.message);
      return result.value;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tenant-channels'] });
    },
  });
};

export const useUpdateChannel = () => {
  const request = useAuthedRequest();
  const queryClient = useQueryClient();
  return useMutation<UpdateChannelResult, Error, UpdateChannelMutation>({
    retry: false,
    mutationFn: async (input) => {
      const envelope = await request<UpdateChannelResult>(
        ENDPOINT.tenant.channel(input.configId as unknown as string),
        {
          method: 'PUT',
          body: {
            routing_address: input.routingAddress,
            credentials: input.credentials,
            webhook_secret: input.webhookSecret,
            status: input.status,
          },
        },
      );
      const result = envelope.result;
      if (isErr(result)) throw new Error(result.error.message);
      return result.value;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tenant-channels'] });
    },
  });
};

export const useVerifyChannel = () => {
  const request = useAuthedRequest();
  const queryClient = useQueryClient();
  return useMutation<VerifyChannelResult, Error, VerifyChannelMutation>({
    retry: false,
    mutationFn: async (input) => {
      const envelope = await request<VerifyChannelResult>(
        ENDPOINT.tenant.verifyChannel(input.configId as unknown as string),
        { method: 'POST' },
      );
      const result = envelope.result;
      if (isErr(result)) throw new Error(result.error.message);
      return result.value;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tenant-channels'] });
    },
  });
};

export const useCreateKnowledgeDocument = () => {
  const request = useAuthedRequest();
  const queryClient = useQueryClient();
  return useMutation<
    CreateKnowledgeDocumentResult,
    Error,
    CreateKnowledgeDocumentMutation
  >({
    retry: false,
    mutationFn: async (input) => {
      const envelope = await request<CreateKnowledgeDocumentResult>(
        ENDPOINT.tenant.knowledge,
        {
          method: 'POST',
          body: {
            title: input.title,
            content: input.content,
            document_type: input.documentType,
            status: input.status,
          },
        },
      );
      const result = envelope.result;
      if (isErr(result)) throw new Error(result.error.message);
      return result.value;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tenant-knowledge'] });
    },
  });
};

export const useUpdateKnowledgeDocument = () => {
  const request = useAuthedRequest();
  const queryClient = useQueryClient();
  return useMutation<
    UpdateKnowledgeDocumentResult,
    Error,
    UpdateKnowledgeDocumentMutation
  >({
    retry: false,
    mutationFn: async (input) => {
      const envelope = await request<UpdateKnowledgeDocumentResult>(
        ENDPOINT.tenant.knowledgeDocument(
          input.documentId as unknown as string,
        ),
        {
          method: 'PUT',
          body: {
            content: input.content,
            status: input.status,
          },
        },
      );
      const result = envelope.result;
      if (isErr(result)) throw new Error(result.error.message);
      return result.value;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tenant-knowledge'] });
    },
  });
};

export const useCreatePolicy = () => {
  const request = useAuthedRequest();
  const queryClient = useQueryClient();
  return useMutation<CreatePolicyResult, Error, CreatePolicyMutation>({
    retry: false,
    mutationFn: async (input) => {
      const envelope = await request<CreatePolicyResult>(
        ENDPOINT.tenant.policies,
        {
          method: 'POST',
          body: {
            policy_type: input.policyType,
            parameters: input.parameters,
            status: input.status,
            effective_from: input.effectiveFrom,
          },
        },
      );
      const result = envelope.result;
      if (isErr(result)) throw new Error(result.error.message);
      return result.value;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tenant-policies'] });
    },
  });
};

export const useUpdatePolicy = () => {
  const request = useAuthedRequest();
  const queryClient = useQueryClient();
  return useMutation<UpdatePolicyResult, Error, UpdatePolicyMutation>({
    retry: false,
    mutationFn: async (input) => {
      const envelope = await request<UpdatePolicyResult>(
        ENDPOINT.tenant.policy(input.policyId as unknown as string),
        {
          method: 'PUT',
          body: {
            parameters: input.parameters,
            status: input.status,
            effective_from: input.effectiveFrom,
          },
        },
      );
      const result = envelope.result;
      if (isErr(result)) throw new Error(result.error.message);
      return result.value;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tenant-policies'] });
    },
  });
};
