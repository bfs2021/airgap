# Airgap — Demo Video Script (< 3 min)

Target length: **~2:40**. Screen recording on macOS: `Cmd+Shift+5` → Record Selected/Entire screen.

## Pre-flight checklist (do this BEFORE recording)
- [ ] Terminal font large (18–22pt), clean theme, window ~100 cols wide.
- [ ] Run the setup once so DataHub Lite is seeded (not on camera):
      `bash scripts/setup_datahub_lite.sh`
- [ ] Do one warm-up run so the Ollama model is loaded (first call is slow):
      `./.venv/bin/airgap audit --source datahub-lite`
- [ ] Clear the terminal (`clear`) and delete `outputs/` so the run looks fresh:
      `rm -rf outputs`
- [ ] Have these ready to open: `outputs/report.md`, `outputs/lineage_graph.html`,
      `outputs/patches/AIRGAP-R1-002.py`.

---

## Storyboard

### Scene 1 — Hook / the problem  (0:00–0:20)
**Screen:** presentation slide 2 ("PII is classified at the source. Then lineage forgets.")
or just talk over a black terminal.
**Say:** "PII gets tagged at the source — but as it flows through pipelines,
the classification doesn't travel with it. It lands untagged in tables nobody
owns. And if you automate the audit with a cloud LLM, you leak the very metadata
you're trying to protect."

### Scene 2 — This is a REAL DataHub  (0:20–0:40)
**Screen:** terminal.
**Run:**
```bash
./.venv/bin/datahub lite list-urns
```
**Say:** "This is a real DataHub — running locally, no Docker. It has our Acme
catalog: datasets, dashboards, an ML feature store."

### Scene 3 — Run the audit  (0:40–1:20)  ← core
**Screen:** terminal.
**Run:**
```bash
./.venv/bin/airgap audit --source datahub-lite
```
**Point at, as it prints:** "Loaded 11 assets… Detection… Explaining findings
locally via Ollama." Then the colored table.
**Say:** "Airgap reads the metadata and lineage, traces PII through the graph,
and finds five governance leaks — ranked by blast radius. Three critical, one
high, one medium. The explanations are written by a local model."

### Scene 4 — The report  (1:20–1:50)
**Screen:** open `outputs/report.md` (VS Code preview, or any Markdown viewer).
**Show:** the summary table, then the first CRITICAL finding.
**Say:** "Each finding has the full lineage evidence — here, `users.email`
flows all the way into `marketing_enriched.email`, untagged, and it's exposed to
a marketing dashboard. Plus a plain-language risk explanation and a fix."

### Scene 5 — The leak map  (1:50–2:10)
**Screen:** open `outputs/lineage_graph.html` in the browser.
**Say:** "The same thing, visually. Red is where PII leaks. You can see it branch
from the customer dimension into four downstream assets — and which ones reach
BI dashboards."

### Scene 6 — The fix, as a PR  (2:10–2:25)
**Screen:** open `outputs/patches/AIRGAP-R1-002.py`.
**Say:** "For every finding, Airgap generates ready-to-run DataHub SDK code —
re-tag the fields, assign an owner. Review it, drop it in a PR."

### Scene 7 — THE PROOF: nothing leaves the machine  (2:25–2:45)  ← climax
**Screen:** click the Wi-Fi icon in the menu bar → **turn Wi-Fi OFF** on camera.
Then terminal.
**Run:**
```bash
./.venv/bin/airgap audit --source datahub-lite
```
**Say:** "And here's the point. Wi-Fi off. It still runs — reads the local
DataHub, detects the leaks, and the local model still writes the explanations.
Nothing ever leaves the machine. That's why you can run Airgap on data you could
never send to a cloud."
**End card:** "Airgap — an air-gapped auditor for the data you can't afford to
leak.  github.com/zelihaguven/airgap"

---

## The exact commands, in order (copy-paste ready)
```bash
cd /Users/ilginguven/airgap

# (off camera) seed + warm up
bash scripts/setup_datahub_lite.sh
./.venv/bin/airgap audit --source datahub-lite
clear && rm -rf outputs

# ON CAMERA
./.venv/bin/datahub lite list-urns            # scene 2
./.venv/bin/airgap audit --source datahub-lite # scene 3
open outputs/report.md                          # scene 4
open outputs/lineage_graph.html                 # scene 5
open outputs/patches/AIRGAP-R1-002.py           # scene 6
# scene 7: turn Wi-Fi OFF, then:
./.venv/bin/airgap audit --source datahub-lite
```

## Tips
- Keep each terminal command visible for a beat before/after it runs.
- If a run feels slow on camera, use `--no-llm` for the *first* audit and save the
  full LLM run for the report/close — but the Wi-Fi-off run should keep the LLM to
  prove local inference.
- Add short on-screen captions for each scene title; it reads well muted.
- Export 1080p, keep it under 3:00 (hard requirement), upload to YouTube/Vimeo as **public**.
