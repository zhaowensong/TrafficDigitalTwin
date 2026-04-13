import json, sys

# Load station locs
with open(r'c:\HKUPRJ\Source\Source\data\base2info.json', 'r', encoding='utf-8') as f:
    base2info = json.load(f)
print(f"base2info.json: {len(base2info)} entries")

# Load trajectories and get all unique base_ids
with open(r'c:\HKUPRJ\Source\user_data_shanghai_v1\trajectories.json', 'r', encoding='utf-8') as f:
    traj_data = json.load(f)

all_base_ids = set()
for u in traj_data['users']:
    for t in u['trajectory']:
        if len(t) >= 4 and t[3] is not None:
            all_base_ids.add(t[3])

print(f"Unique base_ids in trajectories: {len(all_base_ids)}")

# Check mapping
mapped = all_base_ids & set(int(k) for k in base2info.keys())
unmapped = all_base_ids - set(int(k) for k in base2info.keys())
print(f"Mapped (in base2info): {len(mapped)}")
print(f"Unmapped (NOT in base2info): {len(unmapped)}")
print(f"Match rate: {len(mapped)/len(all_base_ids)*100:.1f}%")

# Sample unmapped
if unmapped:
    sample = sorted(unmapped)[:20]
    print(f"\nSample unmapped base_ids: {sample}")

# Check extended
try:
    with open(r'c:\HKUPRJ\Source\Source\data\base2info_extended.json', 'r', encoding='utf-8') as f:
        base2info_ext = json.load(f)
    print(f"\nbase2info_extended.json: {len(base2info_ext)} entries")
    mapped_ext = all_base_ids & set(int(k) for k in base2info_ext.keys())
    unmapped_ext = all_base_ids - set(int(k) for k in base2info_ext.keys())
    print(f"Mapped (in extended): {len(mapped_ext)}")
    print(f"Unmapped (NOT in extended): {len(unmapped_ext)}")
    print(f"Match rate: {len(mapped_ext)/len(all_base_ids)*100:.1f}%")
except:
    print("No extended file found")
