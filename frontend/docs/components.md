# Components

The reusable UI library in `src/components/`. Each component is its own directory with
`index.tsx`, a co-located `styles.module.css`, and often a `*.stories.ts(x)`. Styling
follows `DESIGN.md` (the authority) and design tokens in `src/index.css`.

## Rules (from DESIGN.md)

- **Tokens only.** Every color, spacing, radius, and shadow references a CSS custom
  property (`var(--…)`) defined in `src/index.css`. No raw hex or magic pixel values in
  component CSS. `DESIGN.md` §2 lists the canonical token set.
- **BEM class names.** `block__element--modifier`, one `styles.module.css` per
  component (CSS Modules). `DESIGN.md` §10.
- **Light mode only, dark-ready.** The app ships light-only; because everything flows
  through tokens, dark mode is a future token-value swap, not a rewrite. Don't hardcode
  colors.
- **Accessibility is part of "done."** Contrast, focus rings, keyboard support — see
  `DESIGN.md` §9.

Read `DESIGN.md` before writing or editing any component CSS.

## Catalog

Components live under `src/components/<Name>/`. Grouped by role:

**Primitives & forms** — `Button`, `Select`, `Dropdown`, `TagInput`, `FileDropzone`,
`Pagination`, `Table`, `Card`, `StatCard`.

**Feedback & status** — `Toast` (paired with the `useToast` hook), `LoadingSpinner`,
`ProgressBar`, `ProcessingBadge`, `ConfirmDialog`.

**Shell & navigation** — `Layout`, `Header`, `Sidebar`, `Logo`, `UserAvatar`,
`WorkflowCard`, `WorkflowPageHeader`.

**Workflow-specific** — `ClusterCard`, `ClusterOverlay`, `DraggableTerm`,
`DroppableUnclusteredArea`, `TermOverlay`. These implement the drag-drop clustering UI
with `@dnd-kit` (see [workflow.md](./workflow.md)).

**Auth/routing wrappers** — `AuthProvider`, `ProtectedRoute` (behaviour documented in
[background/routing-and-auth.md](./background/routing-and-auth.md)).

## Charts

`src/components/charts/` wraps Recharts/ECharts into four themed components exported from
`charts/index.ts`: `LineChart`, `BarChart`, `Heatmap`, and `ChartState` (empty/loading/
error state). Shared theme lives in `charts/theme.ts`
(`CHART_TOKENS`, `CHART_PALETTE`, `CHART_FONT_FAMILY`, `PREPARE_CHART_THEME`) so charts
stay on-token. Used mainly by the `Monitor` page.

## Label-category colors

Extraction labels are colored deterministically via `getLabelColorClass(label, labels)`
in `src/utils/labelColors.ts`: a label's index in the dataset's label list maps to one
of nine ramp classes `label1`–`label9` (`index % 9 + 1`; unknown labels fall back to
`label1`). The ramp is defined in `DESIGN.md` §8 / `src/index.css`. Use this helper
rather than assigning colors ad hoc so the same label reads consistently everywhere.

## Stories & tests

Stories sit next to their component (`*.stories.ts(x)`; ~14 today). `npm run test` runs
them in a real Chromium browser via the Vitest **storybook** project (Playwright) — so
stories double as interaction/render tests. See
[setup-and-run.md](./setup-and-run.md#test). Run the story explorer with
`npm run storybook` (:6006).

## Adding a component

1. Create `src/components/<Name>/` with `index.tsx` + `styles.module.css`.
2. Use BEM class names and `var(--…)` tokens only — check `DESIGN.md` for the right
   token/component pattern before inventing one.
3. Add a `*.stories.tsx` covering the main states.
4. Import via the `@components/` path alias.
