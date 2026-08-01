#!/usr/bin/env python3
"""Emit dossier/sections.json — the per-section context the writing-record
viewer needs but the keystroke logs don't carry.

  { "001": {"printed":"1", "order_index":0,
            "motifs":["the sea","the mother"], "labels":[{"text","color"}]}, ... }

Rebuilt whenever motifs, labels, or order change (see `pal build record`)."""
import json, os
import config
from sections import section_paths, load_labels, DOSSIER

# section number -> [motif names]
sec_motifs = {}
for m in config.motifs():
    for s in m["sections"]:
        sec_motifs.setdefault(s, []).append(m["name"])

labels = load_labels()
out = {}
for idx, path in enumerate(section_paths()):
    sid = os.path.basename(path)[:-3]            # "001"
    secnum = int(sid)
    out[sid] = {
        "printed": str(idx + 1),          # positional §-number (order.json order)
        "order_index": idx,
        "motifs": sec_motifs.get(secnum, []),
        "labels": labels.get(sid, []),
    }

with open(os.path.join(DOSSIER, "sections.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=0)
print(f"wrote sections.json · {len(out)} sections · "
      f"{sum(1 for v in out.values() if v['labels'])} labeled")
