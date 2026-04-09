#!/bin/bash
cd /mnt/Data/visitor/TrafficDigitalTwin
source venv/bin/activate
pkill -f "python3 server.py" 2>/dev/null
sleep 2
export PORT=7860
export HOST=0.0.0.0
nohup python3 server.py > server.log 2>&1 &
echo "Server PID: $!"
sleep 15
echo "=== SERVER LOG ==="
tail -40 server.log
echo "=== END LOG ==="
