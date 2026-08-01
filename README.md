# Google Drive Photos Organizer — An Agentic Workflow Example

A practical project demonstrating how to build an **agentic AI workflow** using [LangGraph](https://github.com/langchain-ai/langgraph) for a real-world automation task: organizing, deduplicating, and classifying photos/videos from Google Drive using a local vision model, then freeing up Drive storage.

If you're a data engineer familiar with DAGs and pipeline orchestration (Airflow, Prefect, dbt) but new to agentic workflows, this project bridges that gap with a hands-on example.

## What Makes This "Agentic"?

Traditional pipelines are deterministic: data flows through fixed transformations. Agentic workflows introduce **autonomous decision-making** at runtime — an LLM observes data and decides what to do with it.

In this project, the agent:

| Step | Traditional Pipeline | Agentic Approach |
|------|---------------------|------------------|
| Categorization | Rule-based (file extension, folder name) | Vision model interprets image content and assigns a semantic category |
| Quality filtering | Fixed threshold on resolution | LLM can assess subjective quality (blurry but artistic vs. genuinely bad) |
| Folder descriptions | Template-based (`"{count} files from {date}"`) | LLM summarizes the actual content of each folder in natural language |
| Dedup decisions | Hash match → delete | Perceptual hash detects near-duplicates; agent could reason about which to keep |

The key insight: **not every step needs an LLM**. This project demonstrates a common production pattern — use cheap deterministic filters first (hashing, blur detection), then invoke the expensive model only for decisions that require understanding.

## Architecture: LangGraph as a State Machine

LangGraph models workflows as **directed graphs with typed state**. If you've worked with Airflow DAGs, the mental model is similar — but the nodes can contain LLM calls that make decisions rather than just transforming data.

```
┌─────────┐     ┌─────────────────────┐     ┌──────────┐
│  Fetch  │────▶│ Download & Assess    │────▶│ Classify │
│ (Drive) │     │ (hash, blur, res)    │     │ (vision) │
└─────────┘     └─────────────────────┘     └──────────┘
                                                  │
                                                  ▼
┌─────────┐     ┌──────────┐     ┌────────────────────┐
│ Summary │◀────│  Trash   │◀────│       Decide       │
│         │     │ (Drive)  │     │ (keep vs. discard) │
└─────────┘     └──────────┘     └────────────────────┘
                                        │
                                        ▼
                                  ┌──────────┐
                                  │ Organize │
                                  │ (local)  │
                                  └──────────┘
```

### Key LangGraph Concepts Used

**State** — A Pydantic model (`PipelineState`) that accumulates results as it flows through nodes. Unlike Airflow's XCom, state is first-class and typed:

```python
class PipelineState(BaseModel):
    media_items: list[MediaItem] = []
    processed: list[ProcessedMedia] = []
    to_delete: list[ProcessedMedia] = []
    kept: list[ProcessedMedia] = []
    dry_run: bool = True
```

**Nodes** — Functions that receive state and return a partial update (like a reducer). Each node is a focused unit of work:

```python
def classify_node(state: PipelineState) -> dict:
    # Only classify items that survived quality + dedup filters
    to_classify = [m for m in state.processed if m.quality != "bad"]
    for media in to_classify:
        result = classify_image(media.local_path)  # LLM call
        media.category = result.category
    return {"processed": state.processed}
```

**Edges** — Define execution order. In this project they're linear, but LangGraph supports conditional edges (branching based on state), cycles (retry loops), and parallel fan-out.

### How This Differs from Airflow/Prefect

| Concept | Airflow | LangGraph |
|---------|---------|-----------|
| Unit of work | Task (operator) | Node (function) |
| Data passing | XCom (serialized, limited) | Typed state object (in-memory) |
| Branching | `BranchPythonOperator` | Conditional edges with routing functions |
| Retry/loops | Task-level retry | Graph cycles (edges back to earlier nodes) |
| Human-in-the-loop | External trigger | Built-in interrupt/resume with state persistence |
| Scheduling | Cron-based | External trigger or embedded in a service |

The biggest difference: LangGraph workflows can **pause, ask for input, and resume** — critical when an LLM decision needs human confirmation (e.g., "delete these 200 photos?").

## Project Structure

```
src/
├── workflow.py          # LangGraph graph — Drive direct workflow
├── takeout_workflow.py  # LangGraph graph — Takeout export workflow
├── takeout.py           # Takeout ZIP discovery, download, extraction
├── cli.py               # CLI entry point (Typer)
├── fetcher.py           # Google Drive API integration
├── quality.py           # Deterministic quality checks (OpenCV)
├── dedup.py             # Perceptual hashing for duplicate detection
├── classifier.py        # LLM-powered classification (Ollama)
├── organizer.py         # File system organization + folder summaries
├── models.py            # Pydantic data models
├── config.py            # Environment configuration
└── google_auth.py       # OAuth2 multi-account auth
```

## Concepts to Explore Further

Once you understand this project, natural next steps:

- **Conditional routing** — Add a node that routes videos to a different processing branch than images
- **Human-in-the-loop** — Pause before deletion and show a preview of what will be removed
- **Checkpointing** — Persist state so a failed run resumes from where it stopped (LangGraph supports this natively with `SqliteSaver` or `PostgresSaver`)
- **Parallel processing** — Fan out classification across multiple items concurrently
- **Tool-calling agents** — Instead of a fixed graph, let the LLM choose which tools to call (search for similar photos, look up location data, etc.)

## Running the Project

See [SETUP.md](./SETUP.md) for detailed installation and configuration steps.

Quick start:
```bash
# Install
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Set up Ollama (local vision model — free, private)
ollama pull llava

# Authenticate Google accounts
photos-organizer auth christian
photos-organizer auth wife

# Check storage usage
photos-organizer storage

# Process files directly in Drive
photos-organizer run --execute

# Process Google Photos via Takeout export
# (first: takeout.google.com → Google Photos → deliver to Drive)
photos-organizer takeout --execute
```

## Tech Stack

| Component | Role | Why |
|-----------|------|-----|
| **LangGraph** | Workflow orchestration | Graph-based, typed state, supports cycles and human-in-the-loop |
| **Ollama + LLaVA** | Image classification | Runs locally, no API costs, no data leaves your machine |
| **Google Drive API** | Media source + deletion | List, download, and trash files from multiple accounts |
| **Google Takeout** | Google Photos export | Only viable way to bulk-access Google Photos (API deprecated March 2025) |
| **imagehash** | Duplicate detection | Perceptual hashing catches near-duplicates (crops, resizes) |
| **OpenCV** | Quality assessment | Laplacian variance for blur detection |
| **Pydantic** | Data modeling | Typed state, validation, serialization |
| **Typer + Rich** | CLI | Clean terminal output with progress indicators |

## Design Decisions for Production Readiness

- **Dry run by default** — Nothing is modified without `--execute`
- **Cheap filters first** — Hash and blur checks run before the LLM to minimize compute
- **Largest files first** — Maximizes space freed per item processed
- **All processed files trashed from Drive** — Good files saved locally first; bad quality/duplicates discarded
- **Deletion = trash** — 30-day recovery window in Google Drive
- **Local inference** — No API keys, no costs, no privacy concerns
- **Multi-account** — Handles both accounts with separate OAuth tokens
