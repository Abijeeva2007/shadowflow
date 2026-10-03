# Architecture

One pipeline, run once at startup, served from memory. There is no database:
the API, dashboard, taint, adversary, federation and dossier all read the same
in-memory `DetectionState`.

```mermaid
flowchart LR
    gen["generate_data.py<br/>(seed, noise level)"] -->|"transactions_*.csv<br/>ground_truth.json"| data[("data/ committed")]
    data --> load["load + dedup"]
    load --> graph["graph.build_graph<br/>directed multigraph"]
    graph --> filter["benign_filter<br/>fingerprints -> benign / suspects"]
    filter --> det["pattern detectors<br/>cycles / mule chains / smurfing"]
    det --> score["scoring<br/>0.6 pattern + 0.4 isolation forest"]
    score --> state["DetectionState<br/>(in memory, built once)"]
    state --> api["FastAPI  /api/*<br/>summary rings trace adversary<br/>federation dossier verify"]
    state --> dossier["dossier PDF<br/>hash-chained evidence"]
    dossier --> api
    api --> dash["Next.js dashboard<br/>5 pages, one API_URL"]
    dash --> pdf["dossier.pdf download<br/>+ /api/verify check"]
```

Notes:

- **Startup:** `_ensure_data()` regenerates the CSVs only if they are missing,
  then the pipeline runs once (~1.4 s on the committed data) before the
  server accepts requests. `/health` answers without touching detection
  state.
- **Frontend:** every call goes through `frontend/lib/api.ts`; the base URL
  is baked in at build time from `NEXT_PUBLIC_API_URL`.
- **Deploy:** backend is a Docker image on Render (`render.yaml`), frontend
  is a static build on Vercel; a GitHub Actions cron pings `/health` every
  10 minutes so the free instance stays awake.
- **Dossier:** `/api/rings/{id}/dossier.pdf` builds the PDF and keeps its
  evidence hash chain; `/api/verify/{id}` recomputes the chain from the data
  and reports whether it still matches.
