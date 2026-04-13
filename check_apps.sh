#!/bin/bash
cd /mnt/Data/visitor/TrafficDigitalTwin
source venv/bin/activate

python3 -c "
import requests
# Get a snapshot and extract unique app names
snap = requests.get('http://127.0.0.1:7860/api/simulation/snapshot?t=50').json()
apps = {}
for u in snap['users']:
    name = u[10] if len(u) > 10 else ''
    cat = u[8] if len(u) > 8 else ''
    if name:
        if name not in apps:
            apps[name] = cat
print(f'Total unique apps: {len(apps)}')
print()
# Sort by category
from collections import defaultdict
by_cat = defaultdict(list)
for name, cat in apps.items():
    by_cat[cat].append(name)
for cat in sorted(by_cat.keys()):
    print(f'[{cat}] ({len(by_cat[cat])} apps)')
    for a in sorted(by_cat[cat]):
        print(f'  - {a}')
"
