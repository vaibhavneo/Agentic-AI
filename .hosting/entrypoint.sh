#!/bin/sh
# Container entrypoint for every app on Hugging Face Spaces.
#
#   1. restore the app's data from its private dataset (a no-op when
#      persistence is off; on failure uploads stay disabled - see hf_persist.py)
#   2. start the sync sidecar
#   3. run the app
#   4. on stop: stop the APP first (no more writes), then let the sidecar make
#      its final upload. A plain `exec "$@"` would make the app PID 1, so only
#      it would receive SIGTERM and the sidecar would be killed mid-interval,
#      losing up to one interval of writes.
python3 /app/.hosting/hf_persist.py restore || true
python3 /app/.hosting/hf_persist.py loop &
SYNC=$!
"$@" &
APP=$!
shutdown() {
    kill -TERM "$APP" 2>/dev/null; wait "$APP" 2>/dev/null
    kill -TERM "$SYNC" 2>/dev/null; wait "$SYNC" 2>/dev/null
    exit 0
}
trap shutdown TERM INT
wait "$APP"
code=$?
kill -TERM "$SYNC" 2>/dev/null; wait "$SYNC" 2>/dev/null
exit "$code"
