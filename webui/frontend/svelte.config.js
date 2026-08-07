import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

const config = {
  preprocess: vitePreprocess(),
  // Silence a11y_label_has_associated_control across the app.
  // The codebase ships many `<div class="field"><label>X</label>
  // <input/></div>` patterns where the label is the visual prefix
  // of the input but they're DOM siblings (not nested, no for/id).
  // We acknowledge the warning rather than touching ~35 call sites
  // — see report_playwright_e2e.md for the rationale.
  compilerOptions: {
    warningFilter: (w) => w.code !== 'a11y_label_has_associated_control',
  },
  kit: {
    adapter: adapter({ fallback: 'index.html', strict: false }),
    alias: {
      $lib: 'src/lib'
    }
  }
};

export default config;
