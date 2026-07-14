# Veg-Toon Studio (Hindi सब्ज़ी कार्टून YouTube content studio)

**What it is:** Internal team workspace + playbook for building Hindi vegetable-drama (anthropomorphic sabzi) YouTube channels — competitor teardown, ready-to-shoot AI story scripts (image→I2V), and launch/thumbnail guides. NOT a public product; the site is `noindex`.
**Status:** Active — most recent work 2026-07-14, all pushed + live-verified: (1) **Story 11 thumbnails rebuilt to Playbook 2.0 staged-scene style + desc/tags/keywords packs added** (commit `1e32b9f`; keywords also added to Story 12). (2) **Story 10 RE-SHOT** (commit `d568b9d`): 18 clips → **66**, no dialogue line over 9 Hindi words. Before that: Story 12 built + pushed (commit `02403e5`). Site LIVE (internal): https://danielarnold6136.github.io/veg-toon-studio/

## Live assets
- Repo: **danielarnold6136/veg-toon-studio** (PUBLIC for Pages, but every page is `noindex,nofollow` = internal). Local `origin` remote has an embedded PAT — pushes work as-is; do NOT print/commit it. Collaborators: SilentAurora245 + mary3862jon.
- Live: https://danielarnold6136.github.io/veg-toon-studio/
- Content on disk: `index.html` (teardown/homepage), `stories/story-1..12.html` (**story-10 = RE-SHOT 2026-07-14: 18 beats but 66×10s shots, 113 dialogue lines all ≤9 words, one keyframe per shot, 3 silent reaction shots, ~11:00 — legacy cute full-veg art style, NOT the photoreal style**; **story-11 = narrator-led experiment; thumbnails REBUILT 2026-07-14 to Playbook 2.0 staged scenes (denial / the gate / karma) + desc+tags+keywords added — its 26 beats / 79 shots were NOT touched**; **story-12 = first DIALOGUE-LED hybrid + first photoreal veg-head-on-human script**, built 2026-07-13, 16 beats / 58×8s shots / 41:59 VO:dialogue / ~10–12 min / 10 lip-sync lines / 3 staged-scene thumbnails / title+upload pack), `guides/{story,bgm,thumbnail,launch}-*.html`, `launch/` (meta-launch, postmortem-vegetablesworld, thumbnail-previews/review, video-2), `tracker.html`, `watermark.html`, `updates/2026-07-08.html`, `data/tracker/*.json`.
- Story 12 generator (single source of truth for the page): session scratchpad `s12/{cast,beats_a,beats_b,packs,gen}.py` — edit data files, run `python3 gen.py` to re-emit `stories/story-12.html`. Like story-11's generator it is NOT in-repo.
- Story 10 re-shot generator: session scratchpad `s10/{cast,beats,gen,qa}.py` — `gen.py` splices ONLY the scenes section + full-script + batch-prompt blocks into the shipped `stories/story-10.html` (head/CSS/cast/outro/packs preserved byte-for-byte); `qa.py` asserts the rebuild. **Also NOT in-repo — it dies with the session.** The emitted `stories/story-10.html` is the source of truth; edit the HTML directly next time.

## Key facts
- **Format:** ~5–7 min anthropomorphic vegetable drama (poor-vs-rich + love + betrayal/धोखा + karma), AI-generated image→I2V. Each story page = full Hindi script + scene-mapped image prompts + I2V prompts (Hindi dialogue, English direction).
- **Competitor tracker tooling:** `tools/competitor_pull.py` pulls competitor stats via **Invidious** (server IP is YouTube-bot-flagged so yt-dlp 429s; script rotates/validates Invidious instances, won't overwrite on an empty pull) → dated JSON in `data/tracker/` → regenerates `tracker.html`. Run: `python3 tools/competitor_pull.py`.
- Generator (`build.py`, guides.py, workflow scripts) lives in the SESSION SCRATCHPAD, not this repo — the repo holds the emitted HTML. Rebuild logic is not in-tree.

## Decisions already made
- **PRODUCTION IS VEO3 ONLY** — for BOTH images and video (Dominic, emphatic, 2026-07-09). Do NOT propose or write docs around facelessdev, Kling, Seedance, Midjourney, Flux, DALL·E, Ideogram, or Runway, and no "give me an API key for model X" offers. Thumbnails also come out of Veo3 (Dominic renders + sends them).
- **RENDER LOCK** prompt format (baked into all stories, anti-drift): every image prompt re-states the full anthropomorphic design (can't pin a reusable character); every I2V prompt says "keep EXACTLY the veg from the source image, never turn human, animate only the speaker's mouth"; hard-ban subtitles/captions/text/watermark on every render.
- **Veo3 guardrail bypass:** re-skin trigger words (चोर→"angry crowd/बेईमान", blood→"splash of red paint", जानलेवा→"overcome by heat") — never dull the drama; sweep prompts to 0 triggers. **Confirmed blockers (Story 11, 2026-07-11):** the combo "coughs hard and clutches his chest" (cardiac) + "photo of a child" (child-safety) made Veo3 REFUSE the whole clip. Standing re-skins: **"child"/"children"** → the veg descriptor ("his little apple son", "cheerful young voices") since every character is a fruit/veg anyway; **"clutches his chest"/"coughs hard"** → weary non-medical gesture ("sways, leans on his cart to catch his breath"); **"shoves him"** (violence on an elder) → "bars his way / firmly waves him off"; **"feverish"/"fever"** → "weak, pale / restless half-sleep"; **"collapses"** → "sinks to his knees". Keep benign uses ("clutch the tin/photo to his chest"). Sweep EVERY image+video+thumbnail prompt before shipping.
- **SHOT-ORDER = NARRATION-ORDER (Dominic, 2026-07-11):** within each beat, shots MUST be sequenced in the chronological order of the events the NARRATION describes, and shot number MUST equal play order (1.1 = first on screen) so no manual re-shuffling. QA: read narration → list events → map each shot → confirm order + prop continuity (no appear→vanish→reappear). NOTE: Story 11's script text was independently audited = all 26 beats already correctly ordered — so if Dominic sees images "out of order," it's a RENDER not matching its prompt (regenerate that still), not a script bug. To reorder in the emitted HTML: move the `<div class="shot">` blocks AND renumber shead/labels/`s1-k-` pre-ids + copy-targets.
- **Length knob = BEATS, not words:** ~6 min / ~35 clips; each beat gets 1–3 consecutive ~10s shots (Veo3 = one ~10s clip per image). NEVER trim dialogue words to fit — that kills emotion (angered Dominic).
- **Title formula (corrected 2026-07-13):** YouTube hard-caps titles at **100 UTF-16 units** — total title (hook + tail) must fit inside it; 😭/💔 front-loaded, गरीब/धोखा/kismat-twist pattern, pipe `|`, colon dead; short tail ("Sabji Cartoon | Hindi Kahani"). **Thumbnails (superseded rule):** the old "one giant face ~50%" is DEAD — Playbook 2.0 staged betrayal SCENE is the rule (full frozen story-beat, 2–4 characters, poor↔rich two-camp staging, one wealth prop, split warm/cold light, reads at 120px); verified against the July-2026 1M+ breakout thumbs. Hindi overlay still POST-only (Canva), never AI-rendered.
- **BGM:** avoid NCS (Content-ID claims revenue); use YouTube Audio Library + Pixabay (safe), one shared Suno/Mubert sub for unique per-channel audio.
- **Scaling:** 5–6 channels, everything separated per channel (Google acct + AdSense identity + residential/mobile proxy + antidetect browser); never cross-link.
- **⚠ NARRATOR MODEL CORRECTED (2026-07-13, transcript-measured + adversarially verified):** the "winners run ~80/20 narrator-led" claim from the VW post-mortem is WRONG — 7 of 9 sampled mega-hits (1.4M–7.1M views) are **DIALOGUE-dominant (65–94% dialogue by word share)**, including VW itself (~65–88%). Winners stage dialogue as **ONE external voice track (3–4 voices for all roles) laid over held scenes, loose/no lip-sync** — never per-clip lip-sync. Story 11 (77/23 narrator) stays as-shipped; **Story 12+ = dialogue-led**. Story 12 decisions (Shilpi, 2026-07-13): ~40/60 ratio · **HYBRID voices** (Veo3-native lip-sync ONLY on ~10 spotlight peak lines, ≤12–16 Hindi words each, line ends by ~7s; ALL other dialogue + narration on the external track, mouths closed/neutral in those clips) · runtime target 9:30–10:30 (breakout band is 8:28–13:32, median ~9:20; the 4–6-min cohort stalled/died in June).
- **Veo 3.1 clip cap = 8 SECONDS (4/6/8), NOT ~10s** — all Story-12 prompts say "Single continuous 8-second"; old "~8–10s" pacing is retired for new stories. Prefer hard cuts between fresh 8s clips over Flow Extend. Where the voice track overruns a clip, hold/slow its tail frame in the edit (this is exactly what the winners ship).
- **NEW ART STYLE for Story 12+ (Dominic directive via Bob, 2026-07-13):** photoreal vegetable HEAD on a normal HUMAN body in Indian dress — "whose entire head IS a single real X" phrasing, never "mask/fused/wearing"; confirmed the current winning look on the hottest new channels. **Stories 1–11 keep the legacy cute full-veg lock — do NOT re-render or rewrite them.** Aloo = hero (he leads ~80% of current breakouts; we'd never used him as hero before Story 12). Production still VEO3-ONLY; canonical portrait stills per character (prompts in story-12 cast section) get rendered + approved FIRST (validation pass, incl. one test dialogue clip = shot 4.4), then reused as Flow Ingredients refs (≤3 per scene).
- **Story 12 = "Aloo–Gajar: Modern Family"** — runaway-bride wedding drama (jaimala betrayal, chase = THE thumbnail frame; wedding/love-vs-class is the niche's rising micro-trend as of 2026-07-13). Hard rule from Shilpi: **every thumbnail character must actually appear in the script** (Tamatar cast as Aloo's friend for exactly this reason). Content is genuine general-audience adult melodrama — NOT written for kids (kids watching anyway doesn't change the COPPA label; designing for kids while labelling not-for-kids is the actual violation).
- **Zero-impressions diagnosis (2026-07-13, MFK ruled out — Shilpi confirmed it's OFF):** the AI-content policy is monetization-only, NOT a reach throttle (refuted as the cause). Real mechanism = cold-start starvation: (1) generic titles can't win Search, the only surface a no-history channel has; (2) 3–4 uploads in 2 months = too few algorithm tests (winners ship 3–4×/week); (3) zero external seeding (fix: Shorts teasers + Meta linking each long-form in first 24–48h); (4) CHECK IN STUDIO: video language = Hindi, channel country = India (wrong-language micro-test = 0% CTR = dead test); (5) 5–6-min runtime = half the watch-time per view of the breakouts. Upload checklist baked into story-12.html packs section.
- Moat vs YouTube "inauthentic content" policy (in force 15 Jul 2025) = genuine per-story uniqueness; AI is explicitly allowed, mass-produced sameness is what's targeted.

## ⚠ SHOT/DIALOGUE SIZING RULE (Shilpi, 2026-07-14) — applies to EVERY story
Shilpi's complaint on Story 10: *"dialogues are too long to complete in a 10 sec Veo3 clip; script 9's dialogue length is perfect; script 9 gave 44 scenes, script 10 only 18 — increase the scenes and shorten the dialogue length."*

**Root cause (measured, not guessed):** Story 10 had **18 beats × 1 clip = 18 shots carrying 59 dialogue lines** — 3–4 lines crammed into one ~11s clip, lines up to **24 Hindi words** (≈10.4s of speech: cannot fit ANY Veo clip). Story 9 works because its lines are ~6 words and it runs **1 keyframe PER SHOT**, not per beat.

**The envelope to build every story on (Story 9's, now proven):**
- **1 clip = 10s.** Timing `[0-3s]` action → `[3-7s]` line 1 → `[7-10s]` line 2.
- **No dialogue line over 9 Hindi words.** Line 1 ≤9w, line 2 ≤7w, ≤16w of speech per clip. (Hindi ≈2.3 words/sec.)
- **Max 2 lines per clip.** Never 3–4.
- **One keyframe image prompt + one video prompt PER SHOT** — never one shared keyframe per beat.
- **Shot number = play order** (existing project rule, still holds).
- **To shorten a line: SPLIT it, never cut it.** Dominic's no-trim rule stands — Story 10's rebuild preserved all 618 spoken words while dropping the longest line from 24w → 9w. Splitting a sentence may force a Hindi re-inflection (करने → करनी); that is fine, deleting content is not.
- Shot count falls out of the content: Story 10 needed **66** shots (~11:00 runtime, inside the 8:28–13:32 breakout band), not the 44 Shilpi estimated. Don't force a target count.

**⚠ OPEN RISK — clip length 8s vs 10s.** CLAUDE.md's other decision says Veo 3.1 caps at **8s** (4/6/8). Shilpi was shown that and explicitly chose the **10s** shape anyway (Story 9 renders fine for them at 10s). Story 10 is therefore timed with **line 2 at `[7-10s]`** — meaning **if their Veo returns an 8s clip, line 2 is what gets cut.** If Shilpi reports truncated second lines, re-time to `[0-2s]/[2-5s]/[5-7.5s]` and expect ~85 shots. Do not silently "fix" this — ask.

## ⚠ THUMBNAILS + PACKS — MANDATORY ON EVERY NEW SCRIPT (Shilpi, 2026-07-14)
**Shilpi caught Story 11 shipping OLD-STYLE thumbnails.** Its thumb 2 literally said *"ONE hero face DOMINATES ~half the frame in extreme close-up"*, and the other two were two characters on blurred empty space. That style is **DEAD** and was already superseded by `guides/thumbnail-playbook.html` (**Playbook 2.0 — Story-Scene**). I generated the story after the playbook existed and did not apply it. **Do not repeat this: read `guides/thumbnail-playbook.html` before writing ANY thumbnail prompt.**

**Every thumbnail prompt, in every story, from now on:**
- **A full STAGED SCENE, never a portrait.** 3–4 characters caught mid-drama in a real place. Shilpi, verbatim: *"a proper scene not the empty space (blur space in image) and just two characters — this style is not works."*
- **Sympathy on one side, cruelty on the other.** Victim (crying, ragged, reaching) staged against the rich betrayer(s) (laughing / pointing / turning away). That juxtaposition IS the click.
- **The whole story readable in one frozen beat**, with no text at all (Hindi overlay stays a Canva post-step).
- **ONE clear wealth prop** (luxury car, gold, designer bag), split warm/cold light, reads at 120px.
- **Locked character blocks** (SPECIES / SHAPE & SKIN / FACE NOW / DRESS / DO-NOT, naming the wrong veg) — the anti-drift format.
- **Every character in a thumbnail must actually appear in the script** (standing rule from Story 12).
- Sweep thumbnails for Veo3 trigger words too (`shove`→"bars his way", `collapses`→"sinks to his knees").
- **Thumbnail is the master that attracts the viewer** (Shilpi) — do not treat it as an afterthought.

**Every story page must also ship all four upload packs:** `titles` + **`description`** + **`tags`** + **`keywords`**. Story 11 had only titles; Story 12 had no keywords. Both fixed 2026-07-14. Story 10's packs are the format model (Hindi para → English para → moral → subscribe CTA → AI disclaimer → hashtags).

## 🐞 Two bug classes to sweep in EVERY story (both found in Story 10, 2026-07-14)
1. **Script lines that are never spoken.** The dlg column had lines the I2V prompt silently omitted — verified **7 lines in Story 10** existed on the page but were never rendered (Dada-ji's "शाबाश मेरे लाल...", Munna's "पापा, मेरी फ़ीस...?", Shimla's "हम्म... ठीक है...", Baingan's "छोटे से शुरू कर...", Bhindi's "कर्ज़ उतर गया...", +2). **Check stories 1–9 and 11 for the same.** QA: every dlg line must appear verbatim inside its own shot's I2V `<pre>`.
2. **Character gender mismatch between image and video prompts.** Story 10's image prompts described Shimla Mirch as male ("his smug shine", "kneeling beside him") while **all 16** of his I2V lines said *"only her mouth moving"* → guaranteed render drift. **Sweep every story for speaker-gender consistency across img vs i2v.**

## Dead ends — do NOT redo
- Non-Veo3 tools in any new doc (see decision above).
- AI-rendered on-screen text / Devanagari (broken) → all wanted text goes to post overlay.
- Trimming dialogue to hit a runtime.
- yt-dlp full extraction from the server (429 — bot-flagged); use Invidious — BUT as of 2026-07-13 the public Invidious/Piped ecosystem was also fully IP-walled from here for API pulls; direct YouTube HTML/RSS fetches + the stored residential-proxy route worked instead.
- "One giant face" thumbnails (superseded by Playbook 2.0 staged scenes).
- Treating "~80/20 narrator-led" as the winning model (refuted by transcript measurement — see corrected decision above).

## Our channel
- **@veggie-toons-tv** — https://www.youtube.com/@veggie-toons-tv (UCID `UCLJ36JTM79XDiTuB2FRvRXA`; Meta handles `@veggietoons_tv` / `@veggietoonstv` in `launch/meta-launch.html`). Do NOT ask for the channel link again.
- State as of 2026-07-13: ~3–4 videos, ~7 total views, near-zero impressions. "Made for Kids" confirmed OFF (Shilpi). Shilpi to send Studio stats — when they arrive, run the language/country settings check from the diagnosis above.

## Next (Story 10 — the live ask from Shilpi)
1. ~~Re-shoot Story 10 (18 → 66 clips, ≤9-word lines)~~ **DONE + pushed + live-verified 2026-07-14** (`d568b9d`). Legacy cute full-veg art style deliberately KEPT (Story 10 is a stories-1–11 legacy script; the photoreal veg-head style is Story 12+ only).
2. **Shilpi to render a test clip and confirm the 8s-vs-10s question above** — specifically whether the SECOND line of a clip (`[7-10s]`) survives. That single answer decides whether every story needs re-timing.
3. Open: should stories 1–9 + 11 get the same re-shot treatment? Story 10 was the only one flagged, but the two bug classes above (unspoken lines, gender mismatch) are likely present in others — **ask Shilpi before touching them**, they are not to be rewritten unasked.

## Next (Story 12 production — paused while Story 10 is the focus)
1. ~~Push~~ DONE 2026-07-14 (live, 200).
2. VALIDATION PASS before batch-rendering: 7 canonical portraits + test dialogue clip (shot 4.4) — checks seam/mask artifacts, species drift, Hindi lip-sync on a potato mouth, wedding-beat refusals.
3. Record the voice track (4 voices + narrator; doubling map in story-12 cast section), render 58 shots, assemble in shot order.
4. Upload with the packs-section checklist (Hindi language setting, thumbnail A/B, Shorts teasers within 24–48h).

## Closed — do NOT raise again
- **Veo3-only wording sweep of legacy pages: DROPPED (2026-07-13).** Old tool names (facelessdev/Kling/Seedance/Midjourney/Flux/DALL·E) stay as-is in legacy HTML. Never propose this sweep again.
- **`competitor_pull.py` daily/scheduled auto-pull: NO.** Run it ONLY when explicitly asked for a pull. Never schedule it, never offer to.
