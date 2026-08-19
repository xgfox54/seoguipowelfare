# 개인용 복지업무 비서 디자인 시스템

## 0. Research Log

- Concrete reference: [KRDS-MCP](https://github.com/KRDS-MCP/krds-mcp), revision `407fb0105e15f77458754ef0f6f6fb3f3a15a461`.
- Reference files: `data/design-principles.js`, `data/colors.js`, `data/typography.js`, `data/systems.js`, `data/design-tokens.js`, `data/components.js`, `data/patterns-service.js`.
- Product constraint: this is a local personal work tool, not an official government service. Every primary screen must visibly say `개인용 · 비공식` and must not use a government logo or institutional identity.
- Token resolution: KRDS-MCP contains overlapping primary-blue examples (`#0F4C8C` and `#0091FF`). This project standardizes on the Government Blue palette from `data/colors.js`, whose representative value is `#0F4C8C`.

## 1. Direction and principles

The interface is a restrained Korean public-service work surface: clear hierarchy, high legibility, generous touch targets, explicit state feedback, and no decorative motion. The memorable element is the evidence-first answer workspace: a calm Government Blue question panel flows into a source-grounded white document surface.

Apply the seven KRDS principles: user-centered, inclusive, simple, consistent, reliable, context-aware, and easy to use. Optimize for repeated clerical work and older users, with plain Korean copy and WCAG 2.1 AA as the minimum.

## 2. Tokens

### Color

| Token | Value | Use |
| --- | --- | --- |
| `--color-primary-50` | `#E3F2FD` | selected/supporting background |
| `--color-primary-100` | `#BBDEFB` | information boundary |
| `--color-primary-500` | `#0F4C8C` | primary action, key label |
| `--color-primary-600` | `#0C3E74` | hover |
| `--color-primary-700` | `#093158` | active, strong text |
| `--color-primary-900` | `#041E44` | masthead accent |
| `--color-gray-900` | `#212529` | primary text |
| `--color-gray-800` | `#343A40` | heading text |
| `--color-gray-700` | `#495057` | secondary text |
| `--color-gray-600` | `#6C757D` | subdued text |
| `--color-gray-500` | `#ADB5BD` | disabled border |
| `--color-gray-400` | `#CED4DA` | input border |
| `--color-gray-300` | `#DEE2E6` | surface divider |
| `--color-gray-200` | `#E9ECEF` | muted surface |
| `--color-gray-100` | `#F8F9FA` | page background |
| `--color-white` | `#FFFFFF` | card/input background |
| `--color-success` | `#28A745` | normal/complete state |
| `--color-success-light` | `#D4EDDA` | success surface |
| `--color-success-dark` | `#155724` | success text |
| `--color-warning` | `#FFC107` | caution boundary |
| `--color-warning-light` | `#FFF3CD` | caution surface |
| `--color-warning-dark` | `#856404` | caution text |
| `--color-error` | `#DC3545` | validation/error boundary |
| `--color-error-light` | `#F8D7DA` | error surface |
| `--color-error-dark` | `#721C24` | error text |
| `--color-info-light` | `#D1ECF1` | information surface |
| `--color-info-dark` | `#0C5460` | information text |

### Typography

- Family: `Pretendard GOV`, `Pretendard`, system UI, `Noto Sans KR`, `Malgun Gothic`, sans-serif.
- Body: 16px, line-height 1.6. Never render body copy below 16px on mobile.
- Small/meta: 14px, line-height 1.5; reserved for status and supporting metadata.
- Label/body strong: 16px, line-height 1.5, weight 600.
- Section heading: 24px mobile, 28px tablet, 32px desktop; line-height 1.3, weight 700.
- Page title: 28px mobile, 32px tablet, 36px desktop; line-height 1.2, weight 700.
- Preserve Korean semantic phrases where practical; headings must not end with isolated particles or single syllables.

### Spacing, sizing, and shape

- Base unit: 4px. Allowed spacing: 4, 8, 12, 16, 20, 24, 28, 32, 40, 48, 64, 80, 96px.
- Page inline padding: 16px mobile, 24px tablet, 32px desktop.
- Content max width: 1140px. Reading column max width: 760px.
- Touch target: minimum 44px in both dimensions.
- Button: 48px high, 24px horizontal padding, 6px radius.
- Input: minimum 48px control height, 12px horizontal padding, 4px radius.
- Card: 24px padding (16px mobile), 12px radius, 1px neutral border.
- Depth: borders and tonal shifts only. No decorative box shadows.

### Motion

- Only interaction feedback: color/border transitions of 120ms ease-out.
- Loading uses a spinner plus text status; no looping decoration.
- Respect `prefers-reduced-motion: reduce` by removing nonessential transitions.

## 3. Layout contract

- Mobile 320-767px: single column; 16px page padding; action buttons stack when needed.
- Tablet 768-1023px: 24px page padding; status facts may form a two-column grid.
- Desktop 1024px and above: 32px page padding; question workspace uses a `minmax(0, 1fr) 280px` grid with supporting status in the right rail.
- The document owns vertical scrolling. No nested scroll panel for the answer.
- Long Korean text and source paths must wrap without horizontal overflow (`overflow-wrap: anywhere` only for metadata/source identifiers, normal Korean wrapping for prose).

## 4. Accessibility contract

- A visible-on-focus skip link targets the main content.
- One `h1` per page; headings follow hierarchy without skipped levels.
- Every textarea/input has a persistent label, helper text, and programmatic description.
- Character count updates visually; error and loading messages use `role="status"` or `role="alert"` with appropriate `aria-live`.
- Focus indication: 3px Government Blue outline with 2px white offset. Never remove focus without replacement.
- All buttons use native `<button>` elements and expose disabled/busy state.
- Information is not encoded by color alone; every status includes Korean text.
- The primary page warns users not to enter resident registration numbers, phone numbers, addresses, or other personal data.
- Raw model HTML is never trusted. Answer Markdown is rendered server-side with raw HTML disabled.

## 5. Reusable primitives and required states

The `/showcase` route is the state harness. Product screens cannot ship until every primitive below is visible there at 375, 768, and 1280px.

1. `SkipLink`: hidden/rest, keyboard focus.
2. `ServiceHeader`: product title, `개인용 · 비공식` qualifier, healthy/degraded status.
3. `Button`: primary and secondary; rest, hover, focus, active, disabled, busy.
4. `TextareaField`: empty, populated, focus, invalid, disabled; label, helper, count.
5. `StatusBadge`: healthy, warning, error; icon-free text treatment.
6. `Notice`: information, warning, error; semantic role and readable label.
7. `FactList`: model, authentication, document count, indexed section count.
8. `AnswerDocument`: headings, paragraphs, lists, blockquote, code, table, source references.
9. `LoadingState`: spinner, `복지DB를 확인하고 있습니다` text, polite live region.
10. `EmptyState`: concise instructions and suggested-question buttons.

## 6. Product route and state contract

### `/`

- Header: service name and explicit personal/non-official qualifier.
- Intro: `복지 업무 질문` and one-sentence evidence-first guidance.
- Question form: textarea, character count (2-2000), personal-data warning, examples, primary submit and clear actions.
- Status rail: real `/api/status` facts for health, model, authentication, document count, and search section count.
- Answer area states: empty, loading, result, validation error, request/model error.
- Submitting a question moves focus to the result heading after completion; failures move focus to the alert.

### `/showcase`

- All Section 5 primitives and required visual states, using the same production CSS.
- Marked `디자인 시스템 점검용` and not linked as a primary user task.

## 7. Verification matrix

- Viewports: 375x812, 768x1024, 1280x900.
- Pages: `/showcase`, `/` empty state, `/` loading state, `/` answer state, `/` error state.
- Interaction: keyboard tab order, textarea focus/count, example question selection, submit busy/disabled, clear, answer focus, error announcement.
- Content stress: 2,000-character question; long Korean headings; long source filenames; multi-level answer lists; no CJK clipping or horizontal overflow.
- Browser surface must bind only to `127.0.0.1`; no external fonts, scripts, images, analytics, or CDN requests.
