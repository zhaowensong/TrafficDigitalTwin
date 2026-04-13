#!/bin/bash
curl -s 'http://127.0.0.1:7860/api/simulation/snapshot?t=100' | python3 -c "
import sys,json
d=json.load(sys.stdin)
print('total:', d.get('total_users'))
print('schema:', d.get('schema'))
print('handover_count:', d.get('handover_count'))
u=d['users'][0] if d['users'] else []
print('first user:', u)
print('user fields:', len(u))
# Check a few more users for handover
ho_users = [x for x in d['users'] if x[5]==1][:3]
print('handover users sample:', ho_users[:2])
"
