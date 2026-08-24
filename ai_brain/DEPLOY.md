# Deploying the AI Brain

Standard library plus three packages, all in `requirements.txt`: `openai` for
the DeepSeek client, and `sympy` + `numpy` for the Brain Lab. The last two are
not optional — `/api/symbolic`, `/api/matrix` and `/api/descent` raise
ImportError without them, and `research.check_identity()` silently returns
`ok:false` without sympy because its import sits inside a `try/except`.

## Required environment variable

    DEEPSEEK_API_KEY=sk-...

It has to be a real environment variable on the host. `_api_key()` also looks
in `.env` files beside sibling projects, which is how it resolves on the
developer's machine and never will on a deployed box.

Without it everything except "Ask" still works: the Brain Lab and the whole
curriculum are keyless.

## The hosted instance has no book indexes — by design

Retrieval reads the `second_brain` gateway and its 17 `desk-*` indexes. Those
are gigabytes derived from a local book collection, gitignored, and not part
of this deployment. `retrieve_evidence()` degrades deliberately: it returns
`available: False` and the shelf bar says so.

**This is why `curriculum.py` exists.** Its 47 topics are first-class citable
sources tagged `[C:topic-id]`, reaching the professor and the validator alike.
Losing the shelves costs breadth, not grounding.

**Correction (Milestone 1):** pointing `BRAIN_ROOT` at a nonexistent directory
does **not** actually simulate this — `second_brain`'s own module is found via
a path relative to its own file location regardless of `BRAIN_ROOT`, so it
stays importable from inside this monorepo checkout no matter what `BRAIN_ROOT`
points at. The only faithful way to reproduce the bookless condition is the
real deployed instance, or `docker build -t ai-brain .` from this directory —
the build context is `ai_brain/` alone, so the built image genuinely lacks
`second_brain/`, matching production exactly. Verified this way: "Are
interpretable AI and explainable AI the same thing?" matches four curriculum
topics and cites all four, with zero books, in ~48s (down from an earlier
~91s/12,702-token/4-call case caused by a since-fixed bug where a reasoning
call ran on empty evidence anyway).

To restore book grounding, run locally against the indexes or point
`SECOND_BRAIN_ROOT` at a slim subset.

## Topic mastery and conversation history now persist across redeploys

`mastery.py` writes `memory/mastery.db` (stdlib SQLite) and `conversation.py`
writes `memory/conversation.json` — both under the Dockerfile's `/app/memory`
(the working directory is `/app`; `mastery._DB_PATH`/`conversation.py`'s own
path both resolve relative to `Path(__file__).parent`, i.e. `/app`). A
volume (`ai-brain-volume`, 500MB) is attached to the `ai-brain` Railway
service at that exact mount path — added via `railway volume --service
<id> add --mount-path /app/memory` (the sibling `Agentic-AI` service's own
volume, mounted at `/data`, was the precedent for how to do this on this
project, though the mount PATH itself has to match where this app's own code
actually reads/writes, not copy the sibling's path). Verify with `railway
volume list --json` — it should show `serviceName: "ai-brain"`,
`mountPath: "/app/memory"`.

Practical effect: the learner model (known/weak topics, exposure counts,
recurring misconceptions) and the conversation log now survive a `railway
up` or a Railway-initiated restart, the same way they already did when
running locally. Attaching the volume for the first time does not migrate
whatever state existed on the previous, non-persistent disk — there was
nothing worth migrating, since that state was already guaranteed to reset on
the very next redeploy regardless.

**The header badge is honest about which of these happened, not just that a
book search was attempted.** "routed to books" (the query attempted) used to
be the only signal shown, even when retrieval came back empty. It now also
shows what actually grounded the answer: real book passages (green), curriculum
notes only (amber — not retrieved text, said explicitly), web-only (amber), or
general knowledge with no match at all (magenta).

## Verifying a deployment

    python3 tests/smoke_deployment.py https://ai-brain-production-4bd9.up.railway.app

The numeric checks assert closed forms rather than golden output — diag(2,3)
eigenvalues, a singular matrix reporting infinite conditioning and refusing to
invert, power iteration finding 5 on diag(5,1), least squares solving
x+y=3, x−y=1 as (2,1), and the 2/L convergence rule holding in both directions.
A pass means the deployed lab is correct, not just reachable. Exit code is
non-zero on any failure.

`python3 brainlab.py test` runs the same closed-form checks offline, and
`python3 curriculum.py "<question>"` shows which topics a question matches.

## Container

    docker build -t ai-brain .
    docker run --rm -p 8080:8080 -e DEEPSEEK_API_KEY=sk-... ai-brain

466 MB, builds in ~20 s, runs as non-root. `docker compose up -d` reads
`DEEPSEEK_API_KEY` from the environment. Verified by running the 42-check
smoke test against the container, not just by the image building.

Oracle's Always Free shape is Ampere A1 (aarch64); an image built on Apple
Silicon is already correct, and from x86 you need `--platform linux/arm64` or
it dies on the box with "exec format error".

See `deploy/ORACLE.md` for the migration, `deploy/cloud-init.yaml` to provision
the box and `deploy/deploy-oracle.sh` to ship to it.

## Railway

Service `ai-brain` in project **Stock-AI-Agent-VG**. Note the project also
holds `Agentic-AI` (the stock agent) building from the *same* repo — check the
service name before deploying, not the id.

The app lives in `ai_brain/`, so the service needs `rootDirectory` set to
`ai_brain`; historically it was empty and deploys were pushed with `railway up`
from this directory, which is why its deployments carry no commit metadata.

    railway up                       # from ai_brain/
    # or, once the source is connected with rootDirectory=ai_brain:
    railway redeploy --service ai-brain --yes --from-source

`--from-source` matters. Plain `redeploy` re-runs the commit already deployed,
which looks successful and changes nothing.

## Binding

`server.py` reads `$PORT` and binds `0.0.0.0` when `PORT` is present; locally
it stays on `127.0.0.1`.
