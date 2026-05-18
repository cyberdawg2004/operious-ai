/**
 * Multilingual UX dictionary.
 *
 * IMPORTANT ARCHITECTURAL RULE:
 *
 * UI localization ≠ cognition localization. Backend cognition remains
 * canonical English. The dictionary below ONLY affects:
 *   - rendering
 *   - labels
 *   - UX language
 *   - presentation
 *
 * It MUST NEVER:
 *   - translate substrate enum values (those are wire-format and pinned)
 *   - translate session-event kinds (forensic identifiers)
 *   - translate governance verdict tokens (these are operational truth)
 *   - alter any backend-supplied operational meaning
 *
 * Adding a new language is a frontend-only change. The backend never sees it.
 */

export type Locale = 'en' | 'es' | 'ar';

export const SUPPORTED_LOCALES: readonly Locale[] = ['en', 'es', 'ar'];

export const DEFAULT_LOCALE: Locale = 'en';

type DictionaryShape = {
  readonly app: {
    readonly title: string;
    readonly tagline: string;
  };
  readonly nav: {
    readonly operations: string;
    readonly traces: string;
    readonly cognition: string;
    readonly topology: string;
  };
  readonly operations: {
    readonly title: string;
    readonly description: string;
    readonly columns: {
      readonly classification: string;
      readonly title: string;
      readonly status: string;
      readonly raisedAt: string;
      readonly tenant: string;
    };
    readonly empty: string;
  };
  readonly traces: {
    readonly title: string;
    readonly description: string;
    readonly empty: string;
    readonly inputPlaceholder: string;
    readonly inspectAction: string;
  };
  readonly cognition: {
    readonly title: string;
    readonly description: string;
    readonly memoryHeading: string;
    readonly sopHeading: string;
    readonly recommendationsHeading: string;
    readonly approvalRequired: string;
  };
  readonly topology: {
    readonly title: string;
    readonly description: string;
    readonly inspectionEmpty: string;
  };
  readonly common: {
    readonly authorityNotice: string;
    readonly viewDetails: string;
    readonly closeDrawer: string;
  };
};

const en: DictionaryShape = {
  app: {
    title: 'Operious Command Center',
    tagline: 'Frontend visualizes authority. Backend owns it.',
  },
  nav: {
    operations: 'Operations Queue',
    traces: 'Trace Inspector',
    cognition: 'Cognition Hub',
    topology: 'Topology & Governance',
  },
  operations: {
    title: 'Operations Queue',
    description:
      'Human authority recovery surface. Escalations, denied governance verdicts, arbitration deadlocks, topology escalations. Frontend visualizes; the backend authorizes any action.',
    columns: {
      classification: 'Classification',
      title: 'Title',
      status: 'Status',
      raisedAt: 'Raised',
      tenant: 'Tenant',
    },
    empty: 'No queue items observed.',
  },
  traces: {
    title: 'Trace Inspector',
    description:
      'Forensic decision explainability. Session timelines, governance traces, agent execution traces, and replay evidence rendered deterministically.',
    empty: 'Provide a correlation id or session id to inspect a trace bundle.',
    inputPlaceholder: 'Correlation id…',
    inspectAction: 'Inspect',
  },
  cognition: {
    title: 'Cognition Hub',
    description:
      'Governed organizational evolution. Memory proposals, SOP evolution, recommendations, and approval workflows. The frontend never auto-approves.',
    memoryHeading: 'Memory proposals',
    sopHeading: 'SOP evolution proposals',
    recommendationsHeading: 'Operational recommendations',
    approvalRequired: 'Approval is human authority. Backend confirms every decision.',
  },
  topology: {
    title: 'Topology & Governance',
    description:
      'Visual cognition topology. Inspect agents, coordination edges, authority boundaries, and governance attachments. Visualization only — never orchestration.',
    inspectionEmpty: 'Select a node to inspect its substrate metadata.',
  },
  common: {
    authorityNotice: 'Read-only inspection. Mutations require backend confirmation.',
    viewDetails: 'View details',
    closeDrawer: 'Close',
  },
};

const es: DictionaryShape = {
  app: {
    title: 'Centro de mando Operious',
    tagline: 'El frontend visualiza la autoridad. El backend la posee.',
  },
  nav: {
    operations: 'Cola de operaciones',
    traces: 'Inspector de trazas',
    cognition: 'Centro de cognición',
    topology: 'Topología y gobernanza',
  },
  operations: {
    title: 'Cola de operaciones',
    description:
      'Superficie de recuperación de autoridad humana. Escalamientos, gobernanza denegada, bloqueos de arbitraje, escalamientos de topología.',
    columns: {
      classification: 'Clasificación',
      title: 'Título',
      status: 'Estado',
      raisedAt: 'Registrado',
      tenant: 'Tenant',
    },
    empty: 'No se observaron elementos en la cola.',
  },
  traces: {
    title: 'Inspector de trazas',
    description:
      'Explicabilidad forense. Líneas de tiempo de sesión, trazas de gobernanza, trazas de ejecución de agentes y evidencia de replay deterministas.',
    empty: 'Indique un id de correlación o de sesión para inspeccionar una traza.',
    inputPlaceholder: 'Id de correlación…',
    inspectAction: 'Inspeccionar',
  },
  cognition: {
    title: 'Centro de cognición',
    description:
      'Evolución organizativa gobernada. Propuestas de memoria, SOP, recomendaciones y flujos de aprobación. El frontend nunca aprueba automáticamente.',
    memoryHeading: 'Propuestas de memoria',
    sopHeading: 'Propuestas de evolución SOP',
    recommendationsHeading: 'Recomendaciones operativas',
    approvalRequired:
      'La aprobación es autoridad humana. El backend confirma cada decisión.',
  },
  topology: {
    title: 'Topología y gobernanza',
    description:
      'Topología cognitiva visual. Inspeccione agentes, ejes de coordinación, fronteras de autoridad y vínculos de gobernanza. Inspección, nunca orquestación.',
    inspectionEmpty: 'Seleccione un nodo para inspeccionar sus metadatos.',
  },
  common: {
    authorityNotice:
      'Inspección de solo lectura. Las mutaciones requieren confirmación del backend.',
    viewDetails: 'Ver detalles',
    closeDrawer: 'Cerrar',
  },
};

const ar: DictionaryShape = {
  app: {
    title: 'مركز تحكم Operious',
    tagline: 'الواجهة الأمامية تُصوّر السلطة. الخادم يملكها.',
  },
  nav: {
    operations: 'طابور العمليات',
    traces: 'مفتش الأثر',
    cognition: 'مركز الإدراك',
    topology: 'الطوبولوجيا والحوكمة',
  },
  operations: {
    title: 'طابور العمليات',
    description:
      'سطح استرداد السلطة البشرية. التصعيدات، قرارات الحوكمة المرفوضة، حالات الجمود في التحكيم، تصعيدات الطوبولوجيا.',
    columns: {
      classification: 'التصنيف',
      title: 'العنوان',
      status: 'الحالة',
      raisedAt: 'وقت الرفع',
      tenant: 'المستأجر',
    },
    empty: 'لا توجد عناصر مسجّلة.',
  },
  traces: {
    title: 'مفتش الأثر',
    description:
      'قابلية تفسير قرارية بأسلوب جنائي. خطوط زمنية للجلسات، آثار الحوكمة، آثار تنفيذ الوكلاء، أدلة الإعادة بصورة حتمية.',
    empty: 'قدم معرّف ارتباط أو معرّف جلسة لفحص الأثر.',
    inputPlaceholder: 'معرّف الارتباط…',
    inspectAction: 'فحص',
  },
  cognition: {
    title: 'مركز الإدراك',
    description:
      'تطوّر تنظيمي محكوم. مقترحات الذاكرة، تطوّر إجراءات التشغيل، التوصيات وسير الموافقات. الواجهة لا توافق تلقائيًا.',
    memoryHeading: 'مقترحات الذاكرة',
    sopHeading: 'مقترحات تطوير SOP',
    recommendationsHeading: 'توصيات تشغيلية',
    approvalRequired: 'الموافقة سلطة بشرية. الخادم يؤكد كل قرار.',
  },
  topology: {
    title: 'الطوبولوجيا والحوكمة',
    description:
      'طوبولوجيا إدراكية بصرية. افحص الوكلاء، حواف التنسيق، حدود السلطة، وروابط الحوكمة. فحص فقط — وليس تنسيقًا.',
    inspectionEmpty: 'اختر عقدة لفحص بياناتها الوصفية.',
  },
  common: {
    authorityNotice: 'فحص للقراءة فقط. التغييرات تتطلب تأكيد الخادم.',
    viewDetails: 'عرض التفاصيل',
    closeDrawer: 'إغلاق',
  },
};

export const DICTIONARY: Readonly<Record<Locale, DictionaryShape>> = {
  en,
  es,
  ar,
};

export type Dictionary = DictionaryShape;
