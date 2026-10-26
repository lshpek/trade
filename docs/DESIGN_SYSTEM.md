# Design system

## Direction
Calm professional trading terminal; dark-first with restrained accent colors, dense but readable metrics, no decorative fake market charts.

## Tokens
- Background: `#0b1020`; surface: `#121a2b`; elevated surface: `#172238`.
- Text: `#eef3ff`; muted text: `#9eabc3`; border: `#29354c`.
- Accent: `#70a7ff`; positive: `#46c995`; warning: `#f1bd62`; danger: `#ff7785`.
- Radius: 12–18px; spacing scale: 4, 8, 12, 16, 24, 32px.

## UX rules
- Mobile-first, minimum 360px width without horizontal page overflow.
- Every integration shows connected/unavailable/error explicitly.
- Do not use color alone for status; include a label and icon/text.
- Empty and unavailable financial data must not be represented as zero.
- Use real API responses; no fake PnL, positions, or sparkline data.
- All state-changing actions require authorization, CSRF protection, and server-side risk checks; all trade and backtest actions operate strictly in PAPER simulation mode.
