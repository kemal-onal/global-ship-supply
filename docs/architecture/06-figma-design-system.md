# Figma-driven design system

> The frontend uses a small, opinionated design system rooted in the
> maritime / shipping context. The intent is that a designer can edit
> the tokens in Figma and the values flow 1:1 into the React codebase.

---

## 1. Design tokens

Defined in `frontend/tailwind.config.js` and `frontend/src/index.css`.

### 1.1 Color palette

| Token              | Light     | Dark      | Usage                              |
| ------------------ | --------- | --------- | ---------------------------------- |
| `brand.50`         | `#eff6ff` | `#172554` | Subtle backgrounds                 |
| `brand.500`        | `#3b82f6` | `#60a5fa` | Primary buttons, links             |
| `brand.600`        | `#2563eb` | `#3b82f6` | Primary button hover               |
| `brand.700`        | `#1d4ed8` | `#2563eb` | Active state                       |
| `sea.400`          | `#22d3ee` | `#22d3ee` | Decorative — anchors, status       |
| `sea.500`          | `#06b6d4` | `#06b6d4` | Decorative — vessel icons          |
| `ink.50` / `ink.900`| slate-50  | slate-900 | Surfaces (cards, panels)           |
| `ok.500`           | `#10b981` | `#34d399` | Success, active vessel, completed  |
| `warn.500`         | `#f59e0b` | `#fbbf24` | Pending, urgent, in transit        |
| `crit.500`         | `#ef4444` | `#f87171` | Errors, blocking regulation, rejected |

The dark mode is automatic via the `dark` class on `<html>`, controlled
by `useThemeStore` (Zustand) and persisted to `localStorage`.

### 1.2 Typography

- Font: **Inter** (variable), fallback `ui-sans-serif, system-ui`
- Body: 14px / 20px
- H1: 24px / 32px, font-weight 700
- H2: 18px / 28px, font-weight 600
- H3: 16px / 24px, font-weight 600
- Code / SKU: **JetBrains Mono**, fallback `ui-monospace`

### 1.3 Spacing

- Base unit: 4px (Tailwind's default)
- Card padding: 20px
- Page padding: 16/24/32 (mobile/tablet/desktop)
- Section gap: 16px

### 1.4 Radius

- Card: 12px
- Input: 8px
- Button: 8px
- Pill: 9999px

### 1.5 Elevation

- Card: `0 1px 2px rgba(15,23,42,0.04)` light, `0 1px 3px rgba(0,0,0,0.3)` dark
- Dropdown / popover: `0 8px 24px rgba(15,23,42,0.08)`

---

## 2. Component library

Components live in `frontend/src/components/`. Each is intentionally
small and composable.

| Component        | Purpose                                          |
| ---------------- | ------------------------------------------------ |
| `Layout`         | Sidebar + header + outlet; navigates auth state  |
| `ConnectionBadge`| Online/offline + VSAT quality + pending count    |
| `DataGrid`       | Paginated / sortable / filterable rows           |
| `StatusBadge`    | Colored pill for order / RFQ / catering state    |
| `PriorityBadge`  | Colored pill for order priority                  |
| `Field`          | Labeled form field wrapper                       |
| `KPI`            | Dashboard stat card                              |

All components use `clsx` for conditional classes, accept a `className`
prop for one-off overrides, and support dark mode via
`dark:` Tailwind variants.

---

## 3. Figma → code mapping

The Figma source file (not committed) contains:

- A **Foundations** page with color, type, spacing, radius tokens
- A **Components** page mirroring the React component list above
- A **Screens** page with the 12 main pages

The mapping:

| Figma node                 | Code                        |
| -------------------------- | --------------------------- |
| `Color/brand-500`          | `bg-brand-500` Tailwind     |
| `Color/ink-50`             | `bg-white dark:bg-ink-900`  |
| `Type/Heading/H1`          | `text-2xl font-bold`        |
| `Radius/card`              | `rounded-xl` (12px)         |
| `Component/StatusBadge`    | `components/StatusBadge.jsx`|
| `Component/Button/Primary` | `className="bg-brand-600…"` |

When the designer renames a token in Figma, the matching class
changes in one Tailwind config and propagates everywhere.

---

## 4. Iconography

- Library: **lucide-react** (open source, MIT)
- Style: line, 1.5px stroke, currentColor
- Default size: 16px in tables, 20px in cards, 24px in headers

Maritime-specific icons:

- ⚓ Anchor (`Anchor`)
- 🚢 Ship (`Ship`)
- ⛽ Bunkering (text emoji)
- 💧 Fresh water (text emoji)
- 🥕 Provisions (text emoji)
- 🔧 Repair (text emoji)
- ➕ Medical (text emoji)

These are inline rather than in the lucide set because they need
language-neutral recognition for international crews.

---

## 5. Empty / loading / error states

Every async view defines three states:

- **Loading** — centered `<Loader2 className="animate-spin" />`
- **Empty** — illustration + 1-sentence copy + primary CTA
- **Error** — rose-tinted card with the error message and a retry button

Example (Orders.jsx):

```jsx
{isLoading ? <Spinner /> :
 items.length === 0 ? <EmptyState /> :
 <DataGrid items={items} />}
```

---

## 6. Accessibility

- All interactive elements have visible focus rings (`focus:ring-2 focus:ring-brand-500`)
- Color is never the only signal — text labels accompany every status badge
- Tables use `<th scope="col">`, `<caption>`, and row-hover affordance
- Form inputs have associated `<label>` elements
- The toaster respects `prefers-reduced-motion` (no slide-in animation)

---

## 7. Where to extend the system

| New need                  | Where it lives                              |
| ------------------------- | ------------------------------------------- |
| New status color          | `tailwind.config.js` → `colors.<token>`     |
| New data grid column type | `components/DataGrid.jsx` cell renderer     |
| New page                  | `pages/<Name>.jsx` + `App.jsx` route        |
| New icon                  | `lucide-react` (preferred) or inline emoji  |
| New dark-mode token       | Add to `index.css` `:root.dark` block        |
