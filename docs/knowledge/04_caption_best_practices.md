# Caption & Subtitle Best Practices

Category: caption
Source: internal-knowledge-seed
Style: bold, high-contrast, selectively colored, never truncated.

## Line length and line count
Maximum ~18 characters per line in English, at most 2 lines on screen at once. Long lines force a small font that fails on phones held at arm's length. Break at natural phrase boundaries, not mid-clause.

## Auto-fit, never truncate
If a sentence is long, shrink the font until the full text fits within the safe width and 2–4 lines. Never cut with an ellipsis ("…"); a truncated caption reads as a bug and breaks trust. The renderer searches font sizes top-down and picks the largest that fits the whole sentence.

## Selective keyword color (2-accent rule)
Color only the words that carry meaning, with a hard cap of two accent colors per screen. Mapping: ticker = accent_data, positive % = accent_bull, negative % = accent_bear, risk words (risk/overheated/caution/dilution) = accent_alert, source words (Source/Data/As of) = text_secondary. Everything else stays text_primary.

## Outline thickness (captions only)
Captions use a black stroke of 8–12px for legibility over any background. Outline is for captions only — card text, chip labels, and body copy never get an outline (that violates the Terminal Pro look). The outline is what lets a white caption survive a bright photo background.

## Word-by-word fade-in
Words fade in individually (ASS \fad ~80ms) rather than the whole line appearing at once. Sequential reveal paces reading and keeps motion present. The pacing should roughly match the narration so the spoken and on-screen word align.

## Active-word emphasis (karaoke)
The single most important word in a caption gets a scale bounce (\t 1.2→1.0) or a color flip as it is spoken. This directs the eye to the payoff token (the %, the verdict, the ticker) without adding a second accent color.

## Safe zone (MarginV ≥ 250)
Keep captions inside the safe zone: ASS MarginV ≥ 250 and a ~420px bottom reserve. YouTube's like/share/subscribe UI and the persistent disclaimer band live at the bottom; captions placed too low get clipped on-device even though they look fine in the editor.

## Numbers in mono font
Render prices, percentages, RSI, and volume multiples in the mono font (JetBrains Mono). Tabular figures keep digits from reflowing during count-ups and read as "terminal data," reinforcing the credibility positioning.

## Reading-speed budget
Hold a caption at least (characters ÷ 15) seconds. A 36-character two-liner needs ~2.4s minimum. Do not flash a dense caption for under its read time; either hold longer or split across cuts.

## Hedging language preserved
Hedging words stay visible: "likely", "appears", "could", "may", "based on", "as of". They read as expert caution, not weakness, and they are part of the trust posture. Do not "clean them up" into confident phrasing.

## Banned absolute phrasing (lint)
Never display: "will rise", "guaranteed", "must buy", "sure thing", "100%", "easy money". A lint step scans hook/catalyst/risk/payoff text and fails the build if any appear. This protects both credibility and advice-liability.

## Contrast and legibility
White or near-white body text on the dark Terminal Pro background; accents only on keywords. Avoid low-contrast pairings (gray on dark). The caption band uses a translucent dark strip under the text so it stays readable over chart lines and photos.

## Alignment
Captions and body text are left-aligned by default; only the hook headline and the huge number are centered. Left alignment scans faster and looks editorial; centering everything looks like a meme template.

## Punctuation and casing
Sentence case for captions (not ALL CAPS) except short labels/badges (DURABLE, URGENT, VS). ALL CAPS body text lowers readability and raises the "hype" feel the channel avoids. Reserve caps for single-word emphasis tokens.
