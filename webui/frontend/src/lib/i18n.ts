import { createI18n } from 'svelte-i18n'

export const i18n = createI18n({
  // Define your locales here
  locales: ['it', 'en'],
  defaultLocale: 'it',
  // Add your translations here
  messages: {
    it: {
      // Add Italian translations
    },
    en: {
      // Add English translations
    }
  }
})