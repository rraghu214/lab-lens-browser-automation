# LabLens — Demo Recording Script

**Target length:** under 4 minutes  
**Query:** *Thyroid Profile (T3, T4, TSH) price · Koramangala, Bangalore*  
**Pre-flight:** `python main.py` from `code/`, confirm app at http://localhost:8080. Replay `bc_f847b9ef` pre-loaded in Replay tab.

---

## Before you hit Record

- [ ] `python main.py` running at http://localhost:8080
- [ ] Browser full-screen, light mode, three panels visible
- [ ] Query and locality fields empty (refresh to clear)
- [ ] Ollama running locally (`ollama serve`)
- [ ] `run_artifacts/bc_f847b9ef/replay.json` already loaded in Replay tab
- [ ] GitHub README open in a second browser tab

---

## Scene-by-scene script

### 0:00 — App at rest

**Show:** Full browser — query panel left, empty log centre, empty results right.

**Say:**
> "LabLens compares lab test prices by actually navigating the booking sites — not pulling search snippets. Here's why that matters."

---

### 0:10 — The problem

**Say:**
> "If you HTTP-fetch a site like 1mg, you get a JavaScript shell — the price only appears after you pick a city and search. That's something a static scraper can't do. LabLens solves this with a cascade: it starts with the cheapest approach and steps up only when that approach falls short."

---

### 0:22 — Type the query

**Do:** Type in query and locality fields.

**Say:**
> "Plain English. The agent figures out the sites, the navigation, and the extraction."

---

### 0:30 — Replay tab — Planner DAG

**Do:** Click **Replay** tab. Point to the DAG.

**Say:**
> "The Planner fans out to four sources. Let's walk through what actually happened at each one — and why each needed a different approach."

---

### 0:40 — Practo: Layer 1 fails, Layer 2b succeeds

**Do:** Expand the Practo section.

**Say:**
> "Every source starts at Layer 1 — a plain HTTP fetch, no browser, no LLM, nearly instant. Practo's Layer 1 hit an Akamai security wall — a countdown page with no content."

> "So we escalated to Layer 2b: a real Chromium browser that reads the page's *accessibility tree* — a numbered list of every button, input, and link — and sends that text list to a language model which decides what to click."

> "Three turns waiting for React to hydrate. Then on turn 4, the LLM read element 6 showing 'Thyroid Profile ₹420' and called done immediately — without clicking into any detail page."

**Do:** Click the turn 4 screenshot.

> "₹420. Four turns. 56 seconds."

---

### 1:10 — 1mg: two-field navigation

**Do:** Expand the 1mg section.

**Say:**
> "1mg has a two-field search bar — city on the left, test on the right. Layer 1 gets a JavaScript shell. Layer 2b opens the browser and sees both fields as numbered elements."

> "Turn 1: click city field showing New Delhi. Turn 2: click Bangalore from the dropdown. Turns 4 through 6: type Thyroid Profile in the test field, pick from autocomplete. Turn 8: navigate to the product page. Turn 9: scroll."

**Do:** Click the turn 9 screenshot.

> "₹439 — 20% off ₹550 — on the product page. Conducted by Tata 1mg Labs. 12-hour reports. The cap fired before the agent called done, but the screenshot is the evidence."

---

### 1:45 — Google Maps: Layer 3 vision

**Do:** Expand Google Maps. Show the marked screenshot.

**Say:**
> "Google Maps is a canvas interface — the accessibility tree has almost nothing useful. So we skip to Layer 3: the same browser, but now it takes a full screenshot and uses Pillow to draw numbered dashed boxes over every interactive element. That annotated image goes to a *vision* LLM which reads the lab panel directly from the pixels."

> "One turn. Three labs: Orange Health Labs at 4.9 stars, Mediclive Diagnostics at 4.8, Neuberg Anand Reference Laboratory at 4.8."

---

### 2:10 — Metropolis: honest failure

**Do:** Expand Metropolis.

**Say:**
> "Metropolis — Layer 2b opened the browser, the LLM dismissed a popup, and then the city picker appeared as a fixed overlay that isn't captured in the accessibility tree. The agent can't see it. One turn, cap hit. That's the honest output — the cascade reports what it found and moves on."

---

### 2:25 — Compare tab: two prices

**Do:** Click **Compare** tab.

**Say:**
> "Two confirmed prices: Practo at ₹420 — no coupon, home collection, 24-hour reports. 1mg at ₹439 — 20% already applied, 12-hour reports, and there's a coupon for another 15% off. Three nearby walk-in labs with ratings but no listed prices."

---

### 2:40 — Insights tab

**Do:** Click **Insights** tab.

**Say:**
> "The Distiller synthesises everything. Practo is the lowest no-strings price. 1mg beats it if you apply the coupon. The Insights tab surfaces that trade-off and makes a recommendation."

---

### 2:55 — Replay tab: cost ledger

**Do:** Click **Replay**, scroll to cost ledger.

**Say:**
> "15 turns across four sources. About 27,000 tokens total. Nine minutes elapsed — mostly waiting for JS to render. Estimated cost: zero dollars. Cerebras and GitHub handle the text calls; Ollama handles vision locally."

---

### 3:10 — GitHub README

**Do:** Switch to README tab.

**Say:**
> "The README documents all eight required outputs — goal, DAG, why each layer was chosen, turn-by-turn actions with real LLM thinking text, screenshot references, extracted data, comparison table, and cost summary."

---

### 3:25 — Wrap

**Say:**
> "LabLens — four-layer cascade, live browser navigation, full replay. Thanks for watching."

**Stop recording.**

---

## Editing notes

- Speed-ramp to 4× during log tick lines; resume 1× when a turn result arrives
- Hold on the 1mg turn 9 screenshot for 3–4 seconds — ₹439 needs to register
- Hold on the Google Maps marked screenshot — the numbered boxes are the strongest visual
- Keep the Metropolis moment — an honest partial failure is a stronger demo than hiding it
- Subtitle the LLM thinking lines if the log font is small on export