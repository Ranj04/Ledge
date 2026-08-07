# TASK — wire the three Playbook CTA buttons in the Sales view

Read `.sol/prompts/_context.md` first. It has the project, the constraints and the standing rules.

## Ownership — hard rule

You own and may edit **only**:

```
web/       React SPA
seed/      student generator, fleet data
ablation/  ablation harness
sql/       Snowflake DDL, rollups
scripts/   run scripts (NOT scripts/sol.sh, NOT scripts/experiment.py)
```

Never edit anything under `app/`, `tests/`, or any root-level markdown. **Never run git** — not
`add`, not `commit`, not `checkout`, not `stash`. Fable stages and commits. If you need a change
outside your directories, write it to `.sol/requests/sales-cta-wiring.md` and carry on.

This task is entirely inside `web/src/`.

## The problem

`web/src/SalesView.tsx` implements the `Sales Dashboard.dc.html` mockup from our claude.ai/design
project. It is faithful except for one thing: the Playbook panel's three call-to-action buttons are
inert.

Line ~358 of `web/src/SalesView.tsx`:

```tsx
<button type="button" className="sales-cta">{account.play!.cta}</button>
```

No `onClick`. Clicking does nothing.

In the mockup these are links that navigate to the product demo page. Each one names a destination
that **already exists in our app, on another tab**:

| CTA label | Lives on | Tab |
|---|---|---|
| `Open prompt inspector` | the prompt inspector panel under the tutor chat | `tutor` |
| `Open per-memory ledger` | the per-memory cost table | `dashboard` |
| `Show both layouts` | the naive/tiered comparison in the prompt inspector | `tutor` |

So a rep clicks "Open per-memory ledger" mid-call and lands on the ledger. That is the whole point
of the button and it currently goes nowhere.

## What to do

1. In `web/src/App.tsx`, the view state is `const [view, setView] = useState<...>('tutor')` driving
   the `view-tabs` nav. Pass a navigation callback down: `<SalesView onNavigate={setView} />`.
   Use whatever the existing view union type is — do not invent a new one, and do not widen it.

2. In `web/src/SalesView.tsx`:
   - Add the prop to the component signature. Type it against App's existing view type; if that
     type is not already exported, export it from `App.tsx` (or move it to `types.ts`, your call —
     pick whichever produces less churn) rather than duplicating a string union in two files.
   - Add a `target` field to the `play` object in the `BOOK` constant — `'tutor'` for
     tnt_002131 (`Show both layouts`) and tnt_002069 (`Open prompt inspector`), `'dashboard'` for
     tnt_001236 (`Open per-memory ledger`). Update the `SalesAnnotation` interface to match.
   - Wire the button: `onClick={() => onNavigate(account.play!.target)}`.

3. Make the prop **optional** (`onNavigate?: (view: View) => void`) and no-op safely if absent, OR
   make it required and update every call site. Either is fine — just do not leave a call site that
   type-errors.

Do not restyle anything. Do not touch the four stat cards, the accounts accordion, the ROI
calculator, the quota panel, the alerts panel, or the send-proof panel. Do not change any number,
any copy string, or any colour. This is a wiring change and nothing else.

## Definition of done

- `cd web && npm run build` is clean — no TypeScript errors.
- Start the API from the repo root with `.venv/bin/python -m app` (it serves the built SPA at
  `localhost:8000`), open the **Sales** tab, click the "Playbook" chip if it is not already active,
  expand each of the three playbook rows, and click each CTA. Each must land on the correct tab.
  Rebuild (`npm run build`) before you test — the API serves `web/dist`, not the dev server.
- The Tutor and Dashboard tabs still work after navigating to them this way.
- No new console errors.

Report what you changed and what you verified in your final message. If something blocks you,
write it in `BLOCKERS.md`— no, do not, that is Fable's file. Put blockers in your final message
instead and keep going with the rest.
