# Desktop Action Wait Design

## Intent

Allow Vibana to wait for an asynchronous desktop UI update before capturing the
post-action screenshot used for verification. Search and navigation actions may
finish after the input event has been sent.

## Goals and limits

- Let the desktop planner choose a bounded delay after an action.
- Cap the delay at 10 seconds; default to no delay for ordinary actions.
- Give the explicit `Search for "…"` instruction a 2 second default delay.
- Wait before the existing post-action capture and verification.
- Do not repeat input actions or change the current retry behavior.
- Do not claim that a fixed delay proves a page has finished loading.

## Approaches

- **Planner-selected delay attached to an action (selected):** the planner can
  request a delay only when the action may trigger asynchronous UI work. This
  keeps the existing one-action-per-step flow and lets verification see the
  settled screen.
- **Fixed delay after submitted keyboard input:** simple, but waits on every
  submitted input and gives other slow actions no control over their delay.
- **Standalone wait step:** explicit in a scenario, but the current controller
  stops when the preceding search step fails verification, so it cannot reach
  that wait step without changing step progression.

## Design

Represent the delay as `wait_after_ms` on validated desktop action data, bounded
to 0–10,000 milliseconds. The structured model action response may set it. The
controller sleeps once after executing the action and before capturing the
after-image. The canonical quoted-search instruction is parsed locally and
receives a 2,000 millisecond default. Other actions use zero unless the model or
scenario requests a delay.

The existing verifier, screenshot evidence, and one-shot handling for keyboard
actions remain in place. Tests cover the bound, planner-selected delay, search
default, and ordering before the after-image capture.
