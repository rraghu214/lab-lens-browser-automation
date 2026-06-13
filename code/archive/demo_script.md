# LabLens — Demo Recording Script

**Target length:** under 4 minutes  
**Query to use:** *Compare Thyroid Profile (T3, T4, TSH) prices near Koramangala, Bangalore*  
**Pre-flight:** Start `python main.py` from `code/`, confirm app at http://localhost:8000. Pin browser window and terminal side-by-side or use a single full-screen browser.

---

## Before you hit Record

- [ ] `python main.py` running — app loads at http://localhost:8000
- [ ] Browser at http://localhost:8000, light mode, three panels visible
- [ ] Query and locality fields are empty
- [ ] Previous run results cleared (refresh the page)
- [ ] Ollama running locally (`ollama serve`) — ensures a provider is always available
- [ ] Screen resolution 1920×1080 or 1440×900 — wide enough to show all three panels

---

## Scene-by-scene script

### 0:00 — App at rest

**Show:** Full browser window — query panel on left, empty log panel in centre, empty results on right.

**Say:**  
> "LabLens is a browser agent that compares lab-test prices by actually navigating the booking sites — not scraping search snippets. Let me show you why that matters."

---

### 0:12 — Type the query

**Do:** Click the query textarea. Type:
```
Compare Thyroid Profile (T3, T4, TSH) prices near Koramangala, Bangalore
```
Then click the **Locality** field and type:
```
Koramangala, Bangalore
```

**Say:**  
> "The query goes in plain English. I'll include a locality so it also checks nearby labs."

---

### 0:25 — Click Run, watch the log

**Do:** Click **Run search**.

**Say (as log lines appear):**  
> "Watch the agent log. Each source gets its own entry — the cascade tries the cheapest layer first."

**Pause on Metropolis line:**  
> "Metropolis — Layer 1, static HTML, done in under one second."

**Pause on 1mg line:**  
> "1mg — Layer 1 failed immediately. The price page is JavaScript-rendered. Layer 2b takes over: it opens a real browser, reads the accessibility tree, and navigates step by step."

---

### 0:55 — Zoom into the 1mg turns

**Do:** Zoom into the log panel. Wait for 1mg turns to appear.

**Say (reading the log):**  
> "Turn 1 — nav loaded. Turn 2 — clicked LAB TESTS. Turn 3 — opened the city picker. Turn 4 — selected Bangalore. Turn 5 — typed Thyroid Profile and saw autocomplete results. That's five browser actions, all decided by the LLM reading the accessibility tree."

---

### 1:20 — Google Maps blocked

**Do:** Point to the Google Maps log entry with a `✗` or `⊘`.

**Say:**  
> "Google Maps is blocked — the headless browser was detected. That's not a bug, it's a valid output. The cascade automatically falls back to Practo and JustDial for nearby-lab results."

---

### 1:35 — Thyrocare escalation

**Do:** Point to the Thyrocare entry.

**Say:**  
> "Thyrocare reached search results — you can see the Jaanch Thyroid Profile packages — but then hit a Cloudflare challenge. Layer 2b handed off to Layer 3: a vision model reads a screenshot of the challenge page directly."

---

### 1:55 — Compare tab fills in

**Do:** Click the **Compare** tab in the results panel.

**Say:**  
> "The table fills as each source completes — you don't wait for all eight to finish. Each row arrives the moment the agent extracts it."

**Highlight the recommended card at the top if present:**  
> "The Distiller picked a winner based on price, rating, and review sentiment — with a reason."

---

### 2:20 — Insights tab

**Do:** Click the **Insights** tab.

**Say (read the uTSH note if present, or highlight a key finding):**  
> "The Insights tab is where the reasoning lives. Here — Thyrocare's uTSH is an ultrasensitive assay, clinically different from the standard TSH all other providers offer. That's the kind of thing a price table alone can't tell you."

---

### 2:40 — Replay tab: DAG

**Do:** Click the **Replay** tab. Let the Mermaid diagram load.

**Say:**  
> "The Replay tab gives full post-hoc transparency. This is the Planner DAG — Planner fans out to all eight browser nodes, everything converges at the Distiller, then to the Formatter."

---

### 2:55 — Screenshot thumbnails

**Do:** Scroll to the 1mg or Thyrocare expansion. Click to expand. Point to screenshot thumbnails.

**Say:**  
> "Each source shows the raw extracted data and annotated screenshots — the numbered boxes are the interactive elements the LLM saw when it decided what to click."

**Do:** Click a thumbnail to open the full-size dialog.

**Say:**  
> "You can inspect every turn."

---

### 3:15 — Cost ledger

**Do:** Scroll to the Cost ledger section.

**Say:**  
> "Turn count, token totals, time per source, estimated cost — zero dollars. Every provider used here is on a free tier. Cerebras or Groq get this done in three to five seconds per call when quotas are available; Ollama is the local fallback when they're not."

---

### 3:35 — GitHub README

**Do:** Switch to the browser tab showing the GitHub README (open in advance).

**Say:**  
> "All eight required outputs are in the README — original goal, Planner DAG, browser paths, actions taken, screenshots, extracted data, comparison table, cost summary."

---

### 3:50 — Wrap

**Say:**  
> "LabLens — live browser agent, four-layer cascade, full replay. Thanks for watching."

**Stop recording.**

---

## Editing notes

- Cut dead air during long LLM waits (speed-ramp to 4× while log ticks, then resume 1× when a result arrives)
- Keep the Google Maps blocked moment — it's a strong proof point
- Keep the Thyrocare Layer 3 escalation moment — it's the most dramatic cascade step
- Subtitle the a11y action lines if the log font is too small on export
