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
    warningFilter: (w) => ![
      'a11y_label_has_associated_control',
      // Drag-and-drop calendar + edit mode (audit F1): pointer events
      // are inherent to these interactions. Keyboard alternatives exist
      // where feasible (Escape for cancel, Enter/Space for click).
      // Remaining warnings are edit-mode resize/move drag handles.
      'a11y_no_static_element_interactions',
      'a11y_click_events_have_key_events',
      'a11y_no_noninteractive_element_interactions',
    ].includes(w.code),
  },
  kit: {
    adapter: adapter({ fallback: 'index.html', strict: false }),
    alias: {
      $lib: 'src/lib'
    }
  }
};

export default config;
