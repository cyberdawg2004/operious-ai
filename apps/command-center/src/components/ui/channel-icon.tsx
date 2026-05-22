import type { TenantChannelType } from '@operious/types';
import {
  Mail,
  MessageCircle,
  Bird,
  Phone,
  Globe,
  Cable,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/cn';

const ICON: Record<TenantChannelType, LucideIcon> = {
  email: Mail,
  whatsapp: MessageCircle,
  lark: Bird,
  sms: Phone,
  web_form: Globe,
  api: Cable,
};

const LABEL: Record<TenantChannelType, string> = {
  email: 'Email',
  whatsapp: 'WhatsApp',
  lark: 'Lark',
  sms: 'SMS',
  web_form: 'Web form',
  api: 'API',
};

interface ChannelIconProps {
  readonly kind: TenantChannelType;
  readonly className?: string;
}

export const ChannelIcon = ({ kind, className }: ChannelIconProps) => {
  const Icon = ICON[kind];
  return <Icon className={cn('h-4 w-4', className)} />;
};

export const channelLabel = (kind: TenantChannelType): string => LABEL[kind];
