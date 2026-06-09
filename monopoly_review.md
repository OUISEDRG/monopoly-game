# Monopoly Mini-Game Review

Review date: 2026-06-09

## Issues Fixed

- `run.bat` launched `gen.py`, which does not exist. It now launches `monopoly_app.py`.
- Human player names were inserted into `innerHTML` without sanitization. Names are now stripped of markup characters and escaped before rendering.
- Several UI paths rendered the board twice in a row (`renderBoard(); updateUI();` while `updateUI` also rendered the board). `updateUI` now supports `refreshBoard: false` for call sites that already redrew the board.
- Landing on "go to jail" after rolling doubles could preserve the double-turn behavior. Jail sends now end the turn normally.
- Rent bankruptcy always transferred assets to the richest opponent instead of the creditor. Bankruptcy now prefers the creditor when provided.
- Card side effects could make other players negative without bankruptcy checks. Card resolution now checks all affected players.
- Mobile layout could rely on hidden overflow because the wrapper plus board chrome exceeded the viewport. The mobile board and wrapper sizing now fit within the viewport.

## Verified Behavior

- Game page parses without JavaScript syntax errors.
- Launcher Python compiles successfully.
- Browser setup flow starts the game and renders 40 board cells.
- Custom names containing markup are sanitized and do not execute or inject HTML.
- Rent rules for monopoly, house level, and mortgaged property behave as expected.
- Even-building rules still prevent upgrading one property twice before its group partner.
- Bankruptcy transfers property to the creditor when a creditor exists.
- Desktop and mobile viewport checks show no horizontal document overflow.

## Remaining Optimization Opportunities

- Split the single large HTML file into separate CSS and JavaScript modules for maintainability.
- Replace inline `onclick` attributes with delegated event listeners to reduce global coupling.
- Add deterministic dice/card test hooks so full turn flows can be tested without browser protocol state injection.
- Track the actual creditor for more payment types if future rules add player-to-player card payments beyond the current coverage.
- Add a small favicon or serve `/favicon.ico` with the static server to avoid harmless 404 noise during local static testing.
