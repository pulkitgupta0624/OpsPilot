#!/bin/sh
set -eu

alembic upgrade head

if [ -f data/.demo-bootstrap-complete ]; then
    echo "Demo data, detector, and knowledge index already exist."
    exit 0
fi

opspilot simulate --virtual --normal-only --hours 24 --seed 11
opspilot train --detector rolling_zscore
opspilot kb ingest --index-dir data/rag

touch data/.demo-bootstrap-complete
echo "Demo database, baseline, detector, and knowledge index are ready."
