# Motion & Dynamism Patterns

Category: motion
Source: internal-knowledge-seed
Goal: economy-hunter level energy without real footage. Every cut earns its place.

## Cut cadence
Target 25–30 cuts in a 55–60s video, i.e. an average cut every ~2–2.5s. Data scenes hold ~5s for comprehension but are internally sub-cut (a reveal, an emphasis pulse, a chip highlight) so the frame keeps changing. Energy comes from internal motion plus cut rhythm, not from cutting faster than the eye can read.

## Beat sync fundamentals
Use cinematic or lo-fi BGM at 100–120 BPM. Detect beats once (librosa) and snap every cut start and caption entrance to the nearest beat within ±0.15s. Beat-aligned editing feels intentional and measurably lifts watch time; off-grid cuts feel sloppy even when the visuals are good.

## BPM by mood
100–110 BPM: analytical, "serious data" tone — default for trust-heavy segments. 110–120 BPM: punchy, hype openings and payoff. Match the BGM energy to the scene: calmer under the chart/explainer, more driving under the hook and the result reveal.

## Ken Burns rotation (5 patterns)
Apply one of five slow moves to every static background, cycling so no two consecutive scenes match: zoom_in, zoom_out, pan_left, pan_right, pan_diagonal. Keep the rate gentle (1.05–1.12 scale over the scene) so it reads as cinematic, not jittery.

## Pulse / pop-in entrance
Key elements enter with a scale pulse 0.3 → 1.3 → 0.95 → 1.0 over ~0.3s with alpha 0 → 1, eased on cubic-bezier(0.4,0,0.2,1). Reserve pop-in for the highest-value elements: huge_number, hook_line, payoff_line, durability badge.

## Count-up animation
Hero numbers animate from 0 to the target over ~1.2s with a subtle ticking sound, landing on a ding and a small overshoot. A moving number holds the eye far longer than a static one and dramatizes the magnitude. Use the mono font so digits do not reflow during the count.

## Camera shake on impact
At a genuine shock beat (the result reveal, the risk siren), apply a 0.15s shake of ~8–12px. Cap at 3 shakes per video; more reads as gimmicky and induces fatigue. Pair the shake with an audio hit (ding or alarm) — the combined audio+motion spike is what resets attention.

## Glitch transition (seasoning)
A 0.2s digital glitch is a high-energy alternative to xfade. Use only 2–3 times per video, at section boundaries (hook→body, body→risk, risk→payoff). Overuse cheapens the Terminal Pro tone.

## Typewriter reveal
For longer captions, reveal 2–3 characters per beat so text appears typed live. This keeps motion present during a text-heavy scene and paces reading. Do not typewriter the hook (it must land instantly) — use it on catalyst/explainer lines.

## Mascot idle motion
The mascot is never frozen. Apply a sine bob: amplitude ~8px, period ~2s, optionally a tiny rotation (±1°). This satisfies the no-static rule and keeps the character feeling alive between expression swaps.

## Chart draw-on animation
The price line draws left→right over ~1.2–1.5s, the last point lands a glowing dot, and the final price label pops in. A drawing line is read as "happening now" and outperforms a static chart. After the draw completes, hold with a slow zoom toward the last candle.

## Bar fill with stagger
Comparison bars (volume vs avg, sector co-movers) fill from 0 to value over ~0.8s with a per-bar stagger of ~0.1s. The staggered rise creates a satisfying cascade and lets each value register in sequence. Highlight the focus ticker's bar with an outline after fill.

## Highlight / marker pen sweep
Emphasize a keyword by sweeping a translucent highlight behind it (left→right, ~0.25s) timed to a beat. Cheaper and cleaner than a box; reinforces the one-accent-color rule when the sweep uses the scene's accent.

## Section transitions and whoosh
Each scene boundary carries a short whoosh (~0.3s) layered under the first beat of the new scene. The audio sweep masks the cut and signals "new information," which re-engages attention more reliably than a silent hard cut.

## Zoom punch on reveals
At the exact instant a key value appears, a 0.2s zoom punch (scale 1.0→1.06→1.0) plus a ding draws the eye to the number. Use only on the genuine payoff values, not on every element, or it loses power.

## Parallax depth (subtle)
When a background photo sits behind the mascot, move them at slightly different Ken Burns rates to imply depth. Keep it subtle; strong parallax distracts from the data, which is the real subject.

## Motion budget per scene
Every scene must contain at least one motion primitive (Ken Burns, count-up, draw-on, bar-fill, or typewriter). Shock scenes (result, risk) additionally get a shake. Never ship a scene whose only change is the caption text appearing.
