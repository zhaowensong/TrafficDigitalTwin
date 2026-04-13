#!/usr/bin/env python3
"""Quick check of snapshot data distribution"""
import json, sys, urllib.request

url = "http://localhost:7860/api/simulation/snapshot?t=0"
resp = urllib.request.urlopen(url)
d = json.loads(resp.read())

print(f"Total users in snapshot: {d['total_users']}")
stats = d['station_stats']
users = [s['users'] for s in stats.values()]
print(f"Stations with >=1 user: {len(stats)}")
print(f"User distribution: min={min(users)}, max={max(users)}, avg={sum(users)/len(users):.1f}")

# Histogram
buckets = {'1 user': 0, '2 users': 0, '3 users': 0, '4-10 users': 0, '10+ users': 0}
for u in users:
    if u == 1: buckets['1 user'] += 1
    elif u == 2: buckets['2 users'] += 1
    elif u == 3: buckets['3 users'] += 1
    elif u <= 10: buckets['4-10 users'] += 1
    else: buckets['10+ users'] += 1
print(f"\nStation user count histogram:")
for k, v in buckets.items():
    print(f"  {k}: {v} stations")

# Check t=100 too
url2 = "http://localhost:7860/api/simulation/snapshot?t=100"
resp2 = urllib.request.urlopen(url2)
d2 = json.loads(resp2.read())
print(f"\n--- Compare t=0 vs t=100 ---")
print(f"t=0:   {d['total_users']} users, {len(d['station_stats'])} stations with users")
print(f"t=100: {d2['total_users']} users, {len(d2['station_stats'])} stations with users")

# Check if same station has different stats
common = set(d['station_stats'].keys()) & set(d2['station_stats'].keys())
if common:
    sample = list(common)[:3]
    for sid in sample:
        s0 = d['station_stats'][sid]
        s1 = d2['station_stats'][sid]
        print(f"  Station {sid}: t=0 users={s0['users']} traffic={s0['traffic']:.1f} | t=100 users={s1['users']} traffic={s1['traffic']:.1f}")
