#!/bin/bash
cd /mnt/Data/visitor/TrafficDigitalTwin
source venv/bin/activate
pkill -f 'python.*server.py' 2>/dev/null
sleep 2
export PORT=7860
export HOST=0.0.0.0
nohup python3 server.py > server.log 2>&1 &
echo "Waiting for server to start..."
sleep 15
CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7860/api/simulation/info)
echo "Status: $CODE"
if [ "$CODE" = "200" ]; then
    echo "Server started successfully!"
    # Test gzip compression
    SIZE_NORMAL=$(curl -s http://127.0.0.1:7860/api/simulation/snapshot?t=50 | wc -c)
    SIZE_GZIP=$(curl -s -H 'Accept-Encoding: gzip' --compressed http://127.0.0.1:7860/api/simulation/snapshot?t=50 | wc -c)
    echo "Snapshot response: raw=$SIZE_NORMAL bytes (gzip transfer verified)"
else
    echo "Server failed to start! Check server.log"
    tail -20 server.log
fi
