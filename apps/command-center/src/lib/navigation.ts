import type { LucideIcon } from 'lucide-react';
import {
  Inbox,
  GitFork,
  Brain,
  BookOpen,
  ShieldCheck,
  Network,
  Radio,
  Users,
  FileText,
  Settings,
} from 'lucide-react';

/**
 * Primary navigation registry.
 *
 * The order, labels, and keyboard shortcuts here are the ONE source of truth
 * consumed by:
 *   - the Sidebar component
 *   - the Cmd+K command palette
 *   - the global G-then-key keyboard shortcut handler
 *
 * Routes are pinned to App Router paths. Adding a new top-level page
 * requires adding it here.
 */

export interface NavEntry {
  readonly key:
    | 'operations'
    | 'trace'
    | 'cognition'
    | 'knowledge'
    | 'policies'
    | 'topology'
    | 'channels'
    | 'team'
    | 'audit'
    | 'settings';
  readonly href: string;
  readonly label: string;
  readonly icon: LucideIcon;
  /** G-then-key shortcut (single character). */
  readonly shortcut: string;
  /** Optional sublabel surfaced in the command palette. */
  readonly description?: string;
}

export const NAVIGATION: readonly NavEntry[] = [
  {
    key: 'operations',
    href: '/operations',
    label: 'Operations Queue',
    icon: Inbox,
    shortcut: 'o',
    description: 'Live queue of sessions, escalations, governance verdicts.',
  },
  {
    key: 'trace',
    href: '/trace',
    label: 'Trace Inspector',
    icon: GitFork,
    shortcut: 't',
    description: 'Forensic reconstruction of operational_events trace.',
  },
  {
    key: 'cognition',
    href: '/cognition',
    label: 'Cognition Hub',
    icon: Brain,
    shortcut: 'c',
    description: 'Approval queue for SOP and memory evolution.',
  },
  {
    key: 'knowledge',
    href: '/knowledge',
    label: 'Knowledge Base',
    icon: BookOpen,
    shortcut: 'k',
    description: 'Tenant SOPs, policies, FAQs, escalation matrices.',
  },
  {
    key: 'policies',
    href: '/policies',
    label: 'Governance Policies',
    icon: ShieldCheck,
    shortcut: 'g',
    description: 'Refund limits, RMA thresholds, escalation triggers.',
  },
  {
    key: 'topology',
    href: '/topology',
    label: 'Topology',
    icon: Network,
    shortcut: 'y',
    description: 'Agent topology graph and DAG validation.',
  },
  {
    key: 'channels',
    href: '/channels',
    label: 'Channels',
    icon: Radio,
    shortcut: 'h',
    description: 'Email, WhatsApp, Lark, SMS routing configuration.',
  },
  {
    key: 'team',
    href: '/team',
    label: 'Team & Roles',
    icon: Users,
    shortcut: 'm',
    description: 'Principal directory and capability assignment.',
  },
  {
    key: 'audit',
    href: '/audit',
    label: 'Audit & Exports',
    icon: FileText,
    shortcut: 'a',
    description: 'Audit-relevant activity feed and signed export bundles.',
  },
  {
    key: 'settings',
    href: '/settings',
    label: 'Settings',
    icon: Settings,
    shortcut: 's',
    description: 'Workspace preferences and operator profile.',
  },
] as const;
