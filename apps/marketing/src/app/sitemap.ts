import type { MetadataRoute } from 'next';

const SITE = 'https://operious.ai';

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();
  const sections = [
    '',
    '#kernel',
    '#solutions',
    '#products',
    '#trust',
    '#substrate',
    '#editorial',
    '#newsletter',
    '#faq',
    '#contact',
  ];
  return sections.map((fragment) => ({
    url: `${SITE}/${fragment}`,
    lastModified,
    changeFrequency: 'weekly' as const,
    priority: fragment === '' ? 1 : 0.7,
  }));
}
