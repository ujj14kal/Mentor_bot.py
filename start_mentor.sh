#!/bin/bash
# Eyeconic Mentor System — Auto-start Script
# Restarts on crash with exponential backoff. Stops after 5 rapid crashes.

cd /Users/ujjwalkalra14/MentorBot

CRASH_COUNT=0
MAX_CRASHES=5
WAIT=10

while true; do
    START_TIME=$(date +%s)
    echo "[$(date)] Starting Mentor System (crash count: $CRASH_COUNT)..."

    /usr/bin/python3 mentor_system.py >> data/mentor_stdout.log 2>> data/mentor_stderr.log
    EXIT_CODE=$?

    END_TIME=$(date +%s)
    UPTIME=$((END_TIME - START_TIME))

    # If it ran for less than 60 seconds, count as a crash
    if [ $UPTIME -lt 60 ]; then
        CRASH_COUNT=$((CRASH_COUNT + 1))
        echo "[$(date)] Crashed after ${UPTIME}s (exit code $EXIT_CODE). Crash #$CRASH_COUNT."

        if [ $CRASH_COUNT -ge $MAX_CRASHES ]; then
            echo "[$(date)] Too many rapid crashes ($CRASH_COUNT). Stopping auto-restart."
            echo "[$(date)] Fix the error in mentor.log, then restart manually."
            exit 1
        fi

        # Exponential backoff: 10s, 20s, 40s, 80s, 160s
        WAIT=$((10 * (2 ** (CRASH_COUNT - 1))))
        echo "[$(date)] Waiting ${WAIT}s before restart..."
        sleep $WAIT
    else
        # Ran for a while — reset crash count, use normal restart delay
        CRASH_COUNT=0
        WAIT=10
        echo "[$(date)] Stopped after ${UPTIME}s. Restarting in ${WAIT}s..."
        sleep $WAIT
    fi
done
