# DESIGN.md — Frontend Design Directive

The design directive for the PREPARE Extraction Tool frontend (React 19 + Vite SPA).
It defines the visual system, component rules, domain UI patterns, accessibility baseline,
and CSS authoring conventions that all frontend work must follow.

This document is **prescriptive but grounded**: the system it describes already exists in the
codebase — it just isn't applied uniformly. Where a canonical value is given here, that value
wins. Reconciling existing code to this directive is a separate, deliberate effort; this file is
the target, not a description of current perfection.

---

## 1. Principles

- **Token discipline.** Every color, spacing, radius, and shadow references a CSS custom property
  (`var(--…)`). Raw hex, magic pixel values, and one-off colors are not allowed in component CSS.
  Tokens are defined once in `src/index.css` and consumed everywhere.
- **One coherent system.** The app is a focused workflow tool (extract → cluster → map). Every
  screen should read as the same product: same surfaces, same type scale, same spacing rhythm.
- **Calm, clinical, legible.** This is a data tool for medical/vocabulary work. Favor clarity and
  density-with-breathing-room over decoration. Color carries meaning (state, category), not flourish.
- **Light mode now, dark mode later.** The app ships light-only today. We do **not** build a dark
  theme yet. But *because* all colors flow through tokens, adding a dark theme later is a token-value
  swap (a `:root[data-theme="dark"]` block), not a rewrite. This is the concrete payoff of token
  discipline — do not undercut it with hardcoded colors.
- **Accessibility is not optional.** See §9. Contrast, focus, and keyboard support are part of
  "done," not a later pass.

---

## 2. Design Tokens

All tokens live in `:root` in `src/index.css`. This is the canonical set — the complete intended
token palette, including the neutral ramp and semantic tints that components need day-to-day.

```css
:root {
  /* Brand */
  --color-primary: #144d70;        /* primary actions, active nav, brand */
  --color-primary-dark: #11415e;   /* primary hover; ALL headings; strong brand text */
  --color-accent: #269b6f;         /* link hover, positive accent (== success) */

  /* Semantic — base / hover / tint */
  --color-success: #269b6f;
  --color-success-hover: #20855f;
  --color-success-tint: #d1fae5;
  --color-error: #dc2626;
  --color-error-hover: #b91c1c;
  --color-error-tint: #fef2f2;
  --color-error-border: #fecaca;
  --color-warning: #f59e0b;
  --color-warning-hover: #d97706;
  --color-warning-tint: #fef3c7;
  --color-info: #3b82f6;
  --color-info-hover: #2563eb;
  --color-info-tint: #eff6ff;

  /* Neutral ramp (gray) */
  --color-gray-50: #f9fafb;
  --color-gray-100: #f3f4f6;
  --color-gray-200: #e5e7eb;   /* default border */
  --color-gray-300: #d1d5db;   /* hover border */
  --color-gray-400: #9ca3af;   /* icon / disabled foreground */
  --color-gray-500: #6b7280;   /* muted / secondary text */
  --color-gray-700: #374151;   /* body text */
  --color-gray-900: #1e293b;   /* strongest text on tints */

  /* Semantic aliases */
  --color-text: #374151;
  --color-text-muted: #6b7280;
  --color-border: #e5e7eb;
  --color-surface: #ffffff;      /* cards, drawers, header */
  --color-surface-alt: #f9fafb;  /* zebra rows, subtle fills */
  --color-app-bg: #f8fafc;       /* page background */

  /* Typography */
  --font-family: "Nunito Sans", "Helvetica Neue", Helvetica, Arial, sans-serif;
  --text-xs: 12px;
  --text-sm: 13px;
  --text-base: 14px;   /* default body */
  --text-lg: 16px;
  --text-xl: 18px;
  --text-2xl: 20px;
  --text-3xl: 24px;
  --text-4xl: 28px;
  --weight-regular: 400;
  --weight-medium: 500;
  --weight-semibold: 600;
  --weight-bold: 700;
  --line-height: 1.5;

  /* Spacing (8px rhythm) */
  --space-1: 8px;
  --space-2: 12px;
  --space-3: 16px;
  --space-4: 24px;
  --space-5: 32px;

  /* Radius */
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --radius-xl: 12px;

  /* Elevation */
  --shadow-card: 0 1px 3px rgba(0, 0, 0, 0.08);
  --shadow-drawer: -4px 0 20px rgba(0, 0, 0, 0.15);
  --shadow-overlay: 0 4px 12px rgba(0, 0, 0, 0.15);
}
```

**Rule:** if you need a value that isn't a token (a new tint, a new elevation), add it to `:root`
first, then reference it. Do not inline the literal.

---

## 3. Color

### Brand

| Token | Value | Use |
|-------|-------|-----|
| `--color-primary` | `#144d70` | Primary buttons, active nav item, brand marks |
| `--color-primary-dark` | `#11415e` | Primary hover, **all heading text**, strong labels |
| `--color-accent` | `#269b6f` | Link hover, positive emphasis |

### Semantic

Each semantic color has a **base** (solid fills, icons, borders), a **hover** (darker, for
interactive fills), and a **tint** (pale background for badges, banners, callouts). Text on a tint
uses the corresponding dark ramp/semantic color for contrast.

| Meaning | Base | Hover | Tint |
|---------|------|-------|------|
| Success | `--color-success` | `--color-success-hover` | `--color-success-tint` |
| Error / danger | `--color-error` | `--color-error-hover` | `--color-error-tint` |
| Warning | `--color-warning` | `--color-warning-hover` | `--color-warning-tint` |
| Info | `--color-info` | `--color-info-hover` | `--color-info-tint` |

### Neutrals

The gray ramp is the workhorse: borders, muted text, disabled states, subtle fills. Body text is
`--color-gray-700`; secondary/muted text is `--color-gray-500`; borders are `--color-gray-200`
(rising to `--color-gray-300` on hover). Never introduce a new gray outside the ramp.

### Usage rules

- Page background is `--color-app-bg`; content sits on `--color-surface` cards.
- Color must never be the *only* signal for state — pair with an icon, label, or text (§9).
- Links: default `--color-primary-dark`, hover `--color-accent`.

---

## 4. Typography

Single family: **Nunito Sans** (system sans fallback). Base line-height `1.5`.

### Scale

| Token | Size | Typical use |
|-------|------|-------------|
| `--text-xs` | 12px | Badges, chips, dense metadata |
| `--text-sm` | 13px | Secondary text, footer, table meta |
| `--text-base` | 14px | **Default body**, controls, most UI text |
| `--text-lg` | 16px | Emphasized body, large buttons |
| `--text-xl` | 18px | Section titles, drawer titles |
| `--text-2xl` | 20px | Subsection headings |
| `--text-3xl` | 24px | Workflow page titles |
| `--text-4xl` | 28px | Top-level page titles |

### Weights & headings

- Weights: `400` regular, `500` medium (controls/links), `600` semibold (default for titles,
  badges, table headers), `700` bold (page titles).
- **All headings (`h1`–`h6`) are `--color-primary-dark`.** Do not color headings with other blues.
- Body text is `--color-gray-700`; muted/secondary is `--color-gray-500`.

---

## 5. Spacing, Radius, Elevation

- **Spacing** follows an 8px rhythm (`--space-1`…`--space-5` = 8/12/16/24/32). Use tokens for
  padding, margins, and gaps. Card padding is `--space-4`; grid/flex gaps are typically
  `--space-3`/`--space-4`. Avoid arbitrary pixel gaps.
- **Radius**: `--radius-sm` (4) for small chips/inputs, `--radius-md` (6) for buttons,
  `--radius-lg` (8) for badges, `--radius-xl` (12) for cards.
- **Elevation** is restrained: `--shadow-card` for resting surfaces, `--shadow-overlay` for
  dropdowns/popovers, `--shadow-drawer` for the slide-in drawer. Do not stack shadows or invent
  heavier ones.

---

## 6. Layout & App Shell

- **Container.** Content is centered in a `max-width: 1400px` column with `--space-4` padding and
  `--space-5` gap between nav and main. The app never spans edge-to-edge on wide screens.
- **Left navigation.** Fixed-width primary nav (`180px`) beside the main column. The active item
  uses `--color-primary`.
- **Footer.** Full-width, `--color-surface` background, `--color-gray-500` `--text-sm` text, top
  border `--color-border`.
- **Slide-in drawer (`Sidebar`).** Contextual panels enter from the right on `--color-surface` with
  `--shadow-drawer`, over a `rgba(0,0,0,0.3)` backdrop. Transition `transform 0.3s ease`. Closable
  by backdrop click and Escape (§9).
- **Responsive.** Layout reflows below the container width; the drawer caps at
  `calc(100vw - 80px)`. Content columns must degrade gracefully — no fixed widths that overflow.

---

## 7. Components

Directive-level rules. Each component owns its dir with `index.tsx` + `styles.module.css` (§10).
Build on tokens; do not restyle these ad hoc per page.

- **Buttons.** Variants: `primary`, `secondary`, `success`, `danger`, `warning`, `info`, `ghost`,
  `outline`. Sizes: `small` / `medium` / `large` / `icon`. Radius `--radius-md`, weight `500`,
  `transition: all 0.2s ease`. Fills darken to the `-hover` token on hover; `ghost` underlines;
  disabled is `opacity: 0.5`. Every button has a visible `:focus-visible` ring (§9).
- **Cards.** `--color-surface` on `--color-border`, `--radius-xl`, `--shadow-card`, `--space-4`
  padding. Header is a space-between row; title is `--color-primary-dark`.
- **Tables.** `--color-surface` surface, `--color-border` row separators, semibold header row,
  `--color-surface-alt` zebra/hover. Numeric columns right-aligned. Dense but readable at
  `--text-base`.
- **Forms & inputs.** Inherit the app font. Border `--color-border`, hover `--color-gray-300`,
  focused border/ring in `--color-info`. Labels above fields in `--text-sm`. Error state uses
  `--color-error` border + helper text. Placeholder in `--color-gray-400`.
- **Badges / chips.** Semantic tint background + matching dark foreground, `--radius-lg`,
  `--text-xs`, weight `600`. See §8 for label-category badges.
- **Toasts.** Transient, top-layer, one accent per semantic type (success/error/info/warning) using
  the base color + tint. Auto-dismiss with a manual close.
- **Dialogs (`ConfirmDialog`).** Centered modal on a dimmed backdrop, `--color-surface`,
  `--radius-xl`, `--shadow-overlay`. Destructive confirmations use a `danger` primary button.
  Escape and backdrop dismiss; focus trapped while open (§9).
- **Pagination.** Compact, token-driven; current page uses `--color-primary`.
- **Feedback.** `LoadingSpinner`, `ProgressBar`, `ProcessingBadge` are the canonical progress
  affordances — reuse them, don't reinvent per page.

---

## 8. Domain UI Patterns

These patterns make the tool coherent as a *workflow* app. Rules, not pixel specs.

### Workflow steps (extract → cluster → map)

The dataset workflow is a linear progression. Use `WorkflowPageHeader` for every workflow screen so
the title, step context, and navigation stay consistent. Use `WorkflowCard` for step entry points.
The current step is emphasized with `--color-primary`; completed/upcoming steps read as secondary.
Never build a bespoke page header inside a workflow screen.

### Label category colors (deterministic ramp)

Extracted-term categories are colored by a fixed **9-color ramp** (`label1`–`label9`), assigned
deterministically as `index % 9 + 1`. **Never hand-pick a color for a label** — always derive the
class from the index so the same category is the same color everywhere. Each step has an accessible
dark foreground paired with its pale background.

| Class | Background | Hover | Foreground |
|-------|-----------|-------|-----------|
| `label1` | `#fca5a5` | `#f87171` | `#7f1d1d` |
| `label2` | `#c3f5e2` | `#9befcf` | `#16593f` |
| `label3` | `#d4e6f2` | `#93c1de` | `#13425e` |
| `label4` | `#fcffa7` | `#f5fc28` | `#713f12` |
| `label5` | `#ffd8ef` | `#ff96d3` | `#61103f` |
| `label6` | `#5eead4` | `#2dd4bf` | `#134e4a` |
| `label7` | `#fdba74` | `#fb923c` | `#7c2d12` |
| `label8` | `#c4b5fd` | `#a78bfa` | `#4c1d95` |
| `label9` | `#94a3b8` | `#64748b` | `#1e293b` |

These nine pairs should be promoted to tokens (`--label1-bg`, `--label1-fg`, …) so the ramp has a
single source of truth. Semantic named categories (condition, medication, labtest, procedure,
bodypart) may map onto stable ramp entries.

### Clustering & drag-drop

Semantic clustering (`ClusterCard`, `DraggableTerm`, drop zones) is direct-manipulation. Draggable
terms show a clear grab affordance (cursor, subtle lift on hover: `translateY(-1px)`); drop targets
show an active highlight while a drag is over them; the unclustered area is a visible, labeled
destination. Drag-drop must have a keyboard-accessible equivalent (§9). Transitions stay at
`0.2s ease`.

### State patterns

Every data view accounts for four states, using the shared components — never a blank screen:

- **Loading** → `LoadingSpinner` (or `ProgressBar`/`ProcessingBadge` for long jobs like extraction).
- **Empty** → a centered message + a primary next action (e.g. "Upload a dataset").
- **Error** → `--color-error` messaging with a retry path; never a silent failure.
- **Populated** → the content itself.

---

## 9. Accessibility (cross-cutting)

Applies to every section above.

- **Contrast.** Text meets WCAG AA (4.5:1 body, 3:1 large). The label ramp and semantic tints pair
  pale backgrounds with dark foregrounds specifically to clear this bar — keep those pairings.
- **Color is never the sole signal.** State and category are reinforced with text, icons, or shape,
  so the UI is usable with color-vision deficiency.
- **Focus.** Every interactive element has a visible `:focus-visible` ring
  (`2px solid --color-info`, `outline-offset: 2px`). Do not remove outlines without a replacement.
- **Keyboard.** All actions are keyboard-reachable in a logical tab order. Drawers and dialogs trap
  focus while open, close on Escape, and restore focus to the trigger on close. Drag-drop
  interactions provide a keyboard alternative.
- **Semantics.** Use real semantic elements (`button`, `nav`, `table`, headings in order). Icon-only
  controls need an `aria-label`. Live regions (`aria-live`) announce toasts and job progress.
- **Motion.** Transitions are short (`0.2s`–`0.3s`) and functional. Honor
  `prefers-reduced-motion` for non-essential animation.

---

## 10. CSS Authoring Conventions

How the system is implemented — following these keeps the token rules enforceable.

- **CSS Modules.** One `styles.module.css` per component, imported as `styles`. No global CSS except
  `src/index.css` (tokens + resets). Styles are scoped to their component.
- **BEM naming.** Classes follow `block__element--modifier`:
  `.card`, `.card__header`, `.button--primary`, `.sidebar__backdrop--visible`. Block = component,
  element = child part, modifier = variant/state.
- **Tokens only.** Reference `var(--…)` for color, spacing, radius, shadow, type. **Never** write a
  raw hex, and avoid magic pixel values where a spacing token fits. Need a new value → add a token.
- **Component file structure.** Each component is its own directory:
  `index.tsx` + `styles.module.css` + (often) `*.stories.ts` alongside. New reusable UI follows this
  layout and ships a Storybook story.
- **Composition over duplication.** Reuse the shared components in §7/§8 rather than restyling their
  look per page. If a page needs a new variant, add it to the component, not inline.

---

*This directive is the source of truth for frontend styling. When code and this document disagree,
the document is the target — reconcile the code, not the directive.*
