#!/bin/bash
echo "========================================="
echo "  Backend Performance Report"
echo "========================================="

# 1. Server process resource usage
echo ""
echo "--- 1. Server Process Resource Usage ---"
PID=$(pgrep -f "python.*server.py" | head -1)
if [ -z "$PID" ]; then
    echo "Server not running!"
    exit 1
fi
echo "Server PID: $PID"

# Memory (RSS = physical, VSZ = virtual)
ps -p $PID -o pid,rss,vsz,%mem,%cpu,etime --no-headers | while read pid rss vsz mem cpu time; do
    rss_mb=$((rss / 1024))
    vsz_mb=$((vsz / 1024))
    echo "  Physical Memory (RSS): ${rss_mb} MB"
    echo "  Virtual Memory (VSZ):  ${vsz_mb} MB"
    echo "  Memory %: ${mem}%"
    echo "  CPU %: ${cpu}%"
    echo "  Uptime: ${time}"
done

# Detailed memory breakdown via /proc
echo ""
echo "--- 2. Detailed Memory (/proc/$PID/status) ---"
grep -E "VmRSS|VmSize|VmPeak|VmData|VmStk" /proc/$PID/status 2>/dev/null

# 3. System memory overview
echo ""
echo "--- 3. System Memory ---"
free -h | head -2

# 4. GPU memory
echo ""
echo "--- 4. GPU Memory ---"
nvidia-smi --query-gpu=name,memory.used,memory.total,memory.free,utilization.gpu --format=csv,noheader 2>/dev/null || echo "nvidia-smi not available"

# 5. CPU info
echo ""
echo "--- 5. CPU Info ---"
echo "Cores: $(nproc)"
uptime

# 6. Disk usage for data files
echo ""
echo "--- 6. Data File Sizes ---"
cd /mnt/Data/visitor/TrafficDigitalTwin
echo "  base2info_extended.json: $(du -sh data/base2info_extended.json 2>/dev/null | cut -f1)"
echo "  bs_record_energy.npz:   $(du -sh data/bs_record_energy_normalized_sampled.npz 2>/dev/null | cut -f1)"
echo "  spatial_features.npz:   $(du -sh data/spatial_features.npz 2>/dev/null | cut -f1)"
cd /mnt/Data/visitor/user_data_shanghai_v1
echo "  trajectories.json:      $(du -sh trajectories.json 2>/dev/null | cut -f1)"
echo "  user_profiles_en.json:  $(du -sh user_profiles_en.json 2>/dev/null | cut -f1)"
echo "  profiles_txt/:          $(du -sh profiles_txt/ 2>/dev/null | cut -f1)"

echo ""
echo "========================================="
echo "  API Latency Tests (Server-Side)"
echo "========================================="

# Test each API endpoint with timing (local curl = no network overhead)
echo ""
echo "--- 7. API Response Times (localhost, no network) ---"

# Warm up
curl -s -o /dev/null http://127.0.0.1:7860/api/stations/locations

echo ""
echo "[stations/locations]"
for i in 1 2 3; do
    curl -s -o /dev/null -w "  Run $i: %{time_total}s (connect: %{time_connect}s, server: %{time_starttransfer}s)\n" http://127.0.0.1:7860/api/stations/locations
done

echo ""
echo "[simulation/snapshot?t=0] (first call, no cache)"
curl -s -o /dev/null -w "  Time: %{time_total}s (connect: %{time_connect}s, server_think: %{time_starttransfer}s, size: %{size_download} bytes)\n" "http://127.0.0.1:7860/api/simulation/snapshot?t=0"

echo ""
echo "[simulation/snapshot?t=1]"
curl -s -o /dev/null -w "  Time: %{time_total}s (server_think: %{time_starttransfer}s, size: %{size_download} bytes)\n" "http://127.0.0.1:7860/api/simulation/snapshot?t=1"

echo ""
echo "[simulation/snapshot?t=50]"
curl -s -o /dev/null -w "  Time: %{time_total}s (server_think: %{time_starttransfer}s, size: %{size_download} bytes)\n" "http://127.0.0.1:7860/api/simulation/snapshot?t=50"

echo ""
echo "[simulation/snapshot?t=100]"
curl -s -o /dev/null -w "  Time: %{time_total}s (server_think: %{time_starttransfer}s, size: %{size_download} bytes)\n" "http://127.0.0.1:7860/api/simulation/snapshot?t=100"

echo ""
echo "[simulation/station_locs]"
curl -s -o /dev/null -w "  Time: %{time_total}s (size: %{size_download} bytes)\n" http://127.0.0.1:7860/api/simulation/station_locs

echo ""
echo "[simulation/time_series?station_id=3610000F1752]"
curl -s -o /dev/null -w "  Time: %{time_total}s (server_think: %{time_starttransfer}s, size: %{size_download} bytes)\n" "http://127.0.0.1:7860/api/simulation/time_series?station_id=3610000F1752"

echo ""
echo "[users/stats]"
curl -s -o /dev/null -w "  Time: %{time_total}s\n" http://127.0.0.1:7860/api/users/stats

echo ""
echo "========================================="
echo "  Response Size Analysis"
echo "========================================="
echo ""
echo "[snapshot payload size at different times]"
for t in 0 50 100 200 335; do
    SIZE=$(curl -s "http://127.0.0.1:7860/api/simulation/snapshot?t=$t" | wc -c)
    SIZE_KB=$((SIZE / 1024))
    echo "  t=$t: ${SIZE_KB} KB ($SIZE bytes)"
done

echo ""
echo "Done."
