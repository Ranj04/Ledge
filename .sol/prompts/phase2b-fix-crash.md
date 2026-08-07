# TASK: phase2b-fix-crash — one-line fix, then verify against the live API

Read `/Users/ranjivj/mem/AGENTS.md`. You own `web/`. This is a surgical fix; do not redesign
anything.

## The bug (already diagnosed — do not re-investigate)

`web/src/App.tsx:151`:

```tsx
useEffect(() => endRef.current?.scrollIntoView({ block: 'end' }), [messages])
```

A concise-body arrow **returns** its expression. In current Chrome,
`Element.scrollIntoView({block:'end'})` returns a **Promise**, not `undefined` — verified in the
running browser:

```js
typeof document.querySelector('button').scrollIntoView({block:'end'})  // "object" → [object Promise]
```

React takes that Promise to be the effect's cleanup function. On the next unmount it calls it and
throws `TypeError: destroy_ is not a function` inside `commitHookEffectListUnmount`, which unmounts
the entire tree. **The screen goes black the moment the first message is sent.** The API call
succeeds; the crash is purely in the render.

## The fix

Give the effect a block body so it returns nothing:

```tsx
useEffect(() => {
  endRef.current?.scrollIntoView({ block: 'end' })
}, [messages])
```

Then scan the rest of `web/src/` for any other `useEffect(() => expr, deps)` written with a concise
body and give each a block body too. This is the general form of the bug, not a one-off.

## Then verify it end to end — this is the important half of the task

The API **is running right now** on `http://localhost:8000` with seeded data. Your previous task
could not test against it; this one must.

1. `cd web && npm run build`
2. Drive the built app at `http://localhost:8000` (the FastAPI server serves `web/dist`). Use
   `curl` plus any headless approach you have; if you cannot drive a browser, at minimum use
   `node --experimental-fetch` or `curl` to confirm the endpoints below return what
   `web/src/types.ts` expects, and re-read your rendering code against the real payloads.
3. Confirm this sequence works without a blank screen or a console error:
   - click a starter prompt → tutor text streams in → a receipt line appears under the reply
   - the cost meter's hero number becomes non-zero, "Without tiering" and "Saved" populate
   - the tier strip shows four segments with cached/full-price states
   - flip the toggle to `Naive`, send another message, and the per-call cost bar for that call is
     visibly taller than the tiered ones
   - the prompt inspector renders both columns with cache boundaries marked

Real payloads to check your types against:

```bash
curl -s localhost:8000/api/status
curl -s localhost:8000/api/students
curl -s -X POST localhost:8000/api/inspect -H 'content-type: application/json' \
  -d '{"user_id":"stu_maya_chen","message":"limiting reagents","session_id":"s1"}'
curl -sN -X POST localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"user_id":"stu_maya_chen","session_id":"s1","message":"help with limiting reagents","mode":"tiered"}'
```

Note the first tiered call in a session reports `cost_usd` **higher** than `baseline_cost_usd` —
writing the cache costs 1.25× and there is nothing to read yet. That is correct and honest. The UI
must render a negative "Saved" without breaking layout or showing `NaN`; the second turn onward it
goes positive. Do not clamp it to zero — show the real number.

## Definition of done

- `npm run build` succeeds.
- The sequence above completes with no console error and no blank screen.
- Final message: the fix, any other concise-body effects you found, and what you actually observed
  when you exercised the flow (real numbers, not "should work").
