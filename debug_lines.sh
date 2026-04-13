#!/bin/bash
cd /mnt/Data/visitor/TrafficDigitalTwin
source venv/bin/activate

python3 -c "
import json, requests

# Get station locs (numeric base_id -> [lng, lat])
locs = requests.get('http://127.0.0.1:7860/api/simulation/station_locs').json()
print(f'station_locs keys: {len(locs)} entries')
sample_keys = list(locs.keys())[:5]
print(f'Sample keys: {sample_keys}')
print(f'Key type: {type(sample_keys[0])}')

# Get snapshot
snap = requests.get('http://127.0.0.1:7860/api/simulation/snapshot?t=50').json()
users = snap['users']
print(f'Users: {len(users)}')

# Check base_ids from users
base_ids = set()
for u in users[:100]:
    base_ids.add(str(u[2]))
print(f'Sample user base_ids: {list(base_ids)[:5]}')

# Check how many match
matched = 0
unmatched = 0
for u in users:
    bid = str(u[2])
    if bid in locs:
        matched += 1
    else:
        unmatched += 1
print(f'Matched: {matched}, Unmatched: {unmatched}')
print(f'Match rate: {matched / len(users) * 100:.1f}%')
"
