#!/usr/bin/env python3
"""Check numeric-to-hex ID mapping cardinality"""
import sys, os
sys.path.insert(0, '/mnt/Data/visitor/TrafficDigitalTwin')
os.chdir('/mnt/Data/visitor/TrafficDigitalTwin')

from data_manager import DataManager
dm = DataManager("data", user_data_dir="/mnt/Data/visitor/user_data_shanghai_v1")
dm.load_station_data()
dm.load_user_data()

# Build reverse mapping: hex -> [numeric_ids]
rev = {}
for num_id, hex_id in dm.base_id_to_station_id.items():
    rev.setdefault(hex_id, []).append(num_id)

multi = {k: v for k, v in rev.items() if len(v) > 1}

print(f"Total unique hex station IDs: {len(rev)}")
print(f"Total unique numeric IDs: {len(dm.base_id_to_station_id)}")
print(f"Hex stations with MULTIPLE numeric IDs: {len(multi)}")
print(f"Hex stations with only 1 numeric ID: {len(rev) - len(multi)}")

# Distribution of numeric IDs per hex station
from collections import Counter
counts = Counter(len(v) for v in rev.values())
print(f"\nNumeric IDs per hex station distribution:")
for n, c in sorted(counts.items()):
    print(f"  {n} numeric IDs: {c} hex stations")

# Show a few examples
print(f"\nExamples of multi-ID stations:")
for hex_id, num_ids in list(multi.items())[:3]:
    print(f"  {hex_id} -> {num_ids}")

# KEY ANALYSIS: How many trajectory hex IDs are in the 5326 map stations?
map_hex_ids = set(s['id'] for s in dm.station_list)  # 5326 IDs from NPZ
traj_hex_ids = set(dm.base_id_to_station_id.values())  # 10667 IDs from trajectories

overlap = map_hex_ids & traj_hex_ids
only_map = map_hex_ids - traj_hex_ids
only_traj = traj_hex_ids - map_hex_ids

print(f"\n=== KEY ANALYSIS ===")
print(f"Map stations (NPZ): {len(map_hex_ids)}")
print(f"Trajectory stations: {len(traj_hex_ids)}")
print(f"Overlap (in both): {len(overlap)}")
print(f"Only on map (no users): {len(only_map)}")
print(f"Only in trajectories (not on map): {len(only_traj)}")

# For the overlapping stations, how many users do they capture?
overlap_user_count = 0
non_overlap_user_count = 0
for uid, recs in dm.user_trajectories.items():
    if len(recs) > 0 and len(recs[0]) >= 4:
        base_id = recs[0][3]
        hex_id = dm.base_id_to_station_id.get(base_id)
        if hex_id in overlap:
            overlap_user_count += 1
        else:
            non_overlap_user_count += 1
print(f"\nAt t=0:")
print(f"  Users connected to MAP stations: {overlap_user_count}")
print(f"  Users connected to NON-MAP stations: {non_overlap_user_count}")
print(f"  => {non_overlap_user_count/100:.1f}% of users are 'invisible' to station click")
