#!/bin/bash
# Eyeconic Mentor System — Auto-start Script
# Double-click this file or add it to Login Items to auto-run on boot

cd /Users/ujjwalkalra14/Documents/GitHub/Mentor_bot.py

# Run in background with nohup, restart if it crashes
while true; do
    echo "[$(date)] Starting Mentor System..."
    /Library/Developer/CommandLineTools/usr/bin/python3 mentor_system.py >> data/mentor.log 2>&1
    echo "[$(date)] Mentor System stopped. Restarting in 10 seconds..."
    sleep 10
done
