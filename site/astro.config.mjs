// @ts-check
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
  site: 'https://cartierlist.pages.dev',
  i18n: {
    defaultLocale: 'en',
    locales: ['en', 'da'],
    routing: { prefixDefaultLocale: false },
  },
});
