/**
 * `tooltip` — a Svelte action that shows an explanatory popover after the
 * pointer lingers on an element (~2s by default), or immediately on keyboard
 * focus (accessibility). Used to explain functionalities, domain terms
 * (Cattedra, Compresenza, Potenziamento, Vincolo), and cryptic solver enums
 * (cp_sat_scope, phase_a_mode, …) without cluttering the UI.
 *
 * Usage:
 *   <button use:tooltip={"Explanatory text"}>…</button>
 *   <span use:tooltip={{ text: "…", delay: 1500, placement: 'below' }}>…</span>
 *
 * The popover is portalled to <body>, positioned via the pure
 * `computeTooltipPosition` (unit-tested), styled by `.tt-pop` in app.css,
 * carries role="tooltip", and wires aria-describedby on the anchor while
 * visible. It hides on pointerleave / blur / Escape / scroll. Disabled
 * (text falsy) → no-op. Respects prefers-reduced-motion.
 */

export type TooltipPlacement = 'above' | 'below';

export interface TooltipOptions {
  text: string;
  delay?: number;
  placement?: TooltipPlacement; // preferred; flips if no room
}

interface RectLike {
  left: number;
  right: number;
  top: number;
  bottom: number;
  width: number;
}
interface SizeLike { width: number; height: number; }
interface ViewLike { width: number; height: number; }

export interface TooltipPosition {
  left: number;
  top: number;
  placement: TooltipPlacement;
}

/**
 * Pure placement math (no DOM). Centers the tip horizontally on the anchor,
 * places it `gap` px above by default, flips below when there isn't room
 * above, and clamps horizontally into the viewport. Returns rounded coords.
 */
export function computeTooltipPosition(
  anchor: RectLike,
  tip: SizeLike,
  view: ViewLike,
  gap = 8,
  prefer: TooltipPlacement = 'above',
): TooltipPosition {
  const roomAbove = anchor.top - tip.height - gap >= gap;
  const roomBelow = anchor.bottom + tip.height + gap <= view.height - gap;

  let placement: TooltipPlacement = prefer;
  if (prefer === 'above' && !roomAbove) placement = 'below';
  if (prefer === 'below' && !roomBelow) placement = 'above';

  const top =
    placement === 'above'
      ? anchor.top - tip.height - gap
      : anchor.bottom + gap;

  const anchorCx = anchor.left + anchor.width / 2;
  let left = anchorCx - tip.width / 2;
  const maxLeft = view.width - tip.width - gap;
  if (left < gap) left = gap;
  else if (left > maxLeft) left = Math.max(gap, maxLeft);

  return { left: Math.round(left), top: Math.round(top), placement };
}

let _idSeq = 0;

type TooltipParam = string | TooltipOptions | null | undefined;

function normalize(param: TooltipParam): TooltipOptions | null {
  if (!param) return null;
  if (typeof param === 'string') {
    const t = param.trim();
    return t ? { text: t } : null;
  }
  const t = (param.text ?? '').trim();
  return t ? { ...param, text: t } : null;
}

export function tooltip(node: HTMLElement, param: TooltipParam) {
  let opts = normalize(param);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pop: HTMLDivElement | null = null;
  const id = `tt-${++_idSeq}`;

  const reduceMotion =
    typeof window !== 'undefined' &&
    window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function position() {
    if (!pop) return;
    const a = node.getBoundingClientRect();
    const r = pop.getBoundingClientRect();
    const p = computeTooltipPosition(
      { left: a.left, right: a.right, top: a.top, bottom: a.bottom, width: a.width },
      { width: r.width, height: r.height },
      { width: window.innerWidth, height: window.innerHeight },
      8,
      opts?.placement ?? 'above',
    );
    pop.style.left = `${p.left}px`;
    pop.style.top = `${p.top}px`;
    pop.dataset.placement = p.placement;
  }

  function show() {
    if (pop || !opts) return;
    pop = document.createElement('div');
    pop.className = 'tt-pop';
    pop.id = id;
    pop.setAttribute('role', 'tooltip');
    pop.textContent = opts.text;
    pop.style.position = 'fixed';
    pop.style.left = '-9999px';
    pop.style.top = '0px';
    document.body.appendChild(pop);
    node.setAttribute('aria-describedby', id);
    // Measure then place; reveal on next frame to allow the CSS transition.
    position();
    requestAnimationFrame(() => {
      if (pop) pop.classList.add(reduceMotion ? 'tt-pop--shown-instant' : 'tt-pop--shown');
    });
    window.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide, true);
  }

  function hide() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    if (pop) {
      pop.remove();
      pop = null;
    }
    node.removeAttribute('aria-describedby');
    window.removeEventListener('scroll', hide, true);
    window.removeEventListener('resize', hide, true);
  }

  function scheduleShow() {
    if (!opts || pop) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(show, opts.delay ?? 2000);
  }

  function onEnter() {
    scheduleShow();
  }
  function onLeave() {
    hide();
  }
  function onFocus() {
    // Keyboard users get it immediately (no hover-linger possible).
    if (opts) show();
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') hide();
  }

  node.addEventListener('pointerenter', onEnter);
  node.addEventListener('pointerleave', onLeave);
  node.addEventListener('focusin', onFocus);
  node.addEventListener('focusout', onLeave);
  node.addEventListener('keydown', onKey);

  return {
    update(next: TooltipParam) {
      opts = normalize(next);
      if (!opts) hide();
      else if (pop) {
        pop.textContent = opts.text;
        position();
      }
    },
    destroy() {
      hide();
      node.removeEventListener('pointerenter', onEnter);
      node.removeEventListener('pointerleave', onLeave);
      node.removeEventListener('focusin', onFocus);
      node.removeEventListener('focusout', onLeave);
      node.removeEventListener('keydown', onKey);
    },
  };
}

export default tooltip;
