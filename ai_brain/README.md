# AI Brain

A grounded tutor over the personal library: LLMs, machine learning, mathematics,
robotics, computer vision, Python, electronics, agentic and generative AI.

Same discipline as the Quantum Professor — the pipeline is streamed so it can be
watched, every claim carries the book it came from, and the model is instructed
to say when the library does not cover something rather than filling the gap
quietly.

## Why the search engine is SQLite, not the TF-IDF retriever

`second_brain/retrieve.py` loads a corpus into RAM and scans it linearly.
Measured on one corpus (125,846 chunks) and projected to this library
(~827,000 chunks):

|              | TF-IDF (projected) | FTS5 (measured) |
|--------------|--------------------|-----------------|
| serving RAM  | 9.3 GB             | 13 MB           |
| per query    | 5.1 s              | 4.3 ms          |

FTS5 keeps the index on disk, so breadth is nearly free — every shelf is
searched on every question instead of guessing which one holds the answer.

## Running locally (full library)

    python3 second_brain/fts.py            # build indexes from chunks.json
    python3 ai_brain/server.py --port 5054

## Deployment

The book indexes live on the machine that has the books; they are not shipped.
A deployed instance reports "no library" honestly and answers from general
knowledge — the shelf bar at the top of the page shows which state you are in.

Set `DEEPSEEK_API_KEY`. Optionally `SECOND_BRAIN_ROOT` to point at a checkout
that does have indexes.
