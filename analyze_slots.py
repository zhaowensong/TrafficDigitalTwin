import json

f = open(r'c:\HKUPRJ\Source\user_data_shanghai_v1\trajectories.json', 'r', encoding='utf-8')
d = json.load(f)
users = d['users']

# Handover count per slot
hos = [0] * 336
moves = [0] * 336
stays = [0] * 336
traffics = [0.0] * 336

for u in users:
    traj = u['trajectory']
    for t in range(len(traj)):
        if len(traj[t]) < 12:
            continue
        if traj[t][6] == 'move':
            moves[t] += 1
        else:
            stays[t] += 1
        traffics[t] += (traj[t][10] or 0)
        # handover
        if t > 0 and len(traj[t-1]) >= 4:
            if traj[t][3] != traj[t-1][3]:
                hos[t] += 1

# Find top handover slots
print("=== Handover hotspots (top 20) ===")
ranked = sorted(range(336), key=lambda t: hos[t], reverse=True)[:20]
for t in ranked:
    day = t // 48 + 1
    hh = (t % 48) * 30 // 60
    mm = (t % 48) * 30 % 60
    print(f"t={t:3d} Day{day} {hh:02d}:{mm:02d} | handovers={hos[t]:5d} | move={moves[t]:5d} | traffic={traffics[t]:8.0f} MB")

print("\n=== Day 1 fine-grained (every 30min) ===")
for t in range(48):
    day = t // 48 + 1
    hh = (t % 48) * 30 // 60
    mm = (t % 48) * 30 % 60
    move_pct = moves[t] / 100
    print(f"t={t:3d} {hh:02d}:{mm:02d} | move={moves[t]:5d}({move_pct:4.1f}%) stay={stays[t]:5d} | HO={hos[t]:4d} | traffic={traffics[t]:8.0f} MB")

print("\n=== Best window: transition periods ===")
# Find slots where move count changes most (derivative)
deltas = [abs(moves[t] - moves[t-1]) for t in range(1, 336)]
top_deltas = sorted(range(len(deltas)), key=lambda i: deltas[i], reverse=True)[:10]
for i in top_deltas:
    t = i + 1
    day = t // 48 + 1
    hh = (t % 48) * 30 // 60
    mm = (t % 48) * 30 % 60
    print(f"t={t:3d} Day{day} {hh:02d}:{mm:02d} | delta_move={deltas[i]:5d} | move={moves[t]:5d} | HO={hos[t]:4d}")
