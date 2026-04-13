#!/bin/bash
curl -s 'http://localhost:7860/api/simulation/snapshot?t=0' | python3 -c "
import sys, json
d = json.load(sys.stdin)
ss = d.get('station_stats', {})
print(f'Total stations in stats: {len(ss)}')
vals = list(ss.values())
print(f'First 3 values: {vals[:3]}')
big = [(k, v) for k, v in ss.items() if v['users'] > 10]
big.sort(key=lambda x: -x[1]['users'])
print(f'Stations with >10 users: {len(big)}')
for k, v in big[:5]:
    print(f'  {k}: {v}')
# average
if ss:
    avg_users = sum(v['users'] for v in ss.values()) / len(ss)
    print(f'Average users per station: {avg_users:.1f}')
    total_mapped_users = sum(v['users'] for v in ss.values())
    print(f'Total mapped users: {total_mapped_users}/{d.get(\"total_users\", \"?\")}')
"
