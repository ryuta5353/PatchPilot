import json

print("=" * 80)
print("django__django-11630 の比較: シングル vs 10インスタンス")
print("=" * 80)
print()

# シングルインスタンステスト結果
print("【シングルインスタンステスト】(localization_debug_single3)")
with open("results/localization_debug_single3/loc_outputs.jsonl") as f:
    single_data = json.loads(f.readline())
    single_id = single_data.get('instance_id')
    print(f"Instance ID: {single_id}")
    print(f"Found files: {single_data.get('found_files', [])[:3]}")
    print(f"Found edit locs type: {type(single_data.get('found_edit_locs'))}")
    print()

# 10インスタンステスト結果
print("【10インスタンステスト】(localization_repograph_10inst_stage4_fixed)")
found_target = False
with open("results/localization_repograph_10inst_stage4_fixed/loc_outputs.jsonl") as f:
    for line in f:
        data = json.loads(line)
        if data.get('instance_id') == 'django__django-11630':
            found_target = True
            print(f"Instance ID: {data.get('instance_id')}")
            print(f"Found files: {data.get('found_files', [])[:3]}")
            print(f"Found edit locs type: {type(data.get('found_edit_locs'))}")
            break

if not found_target:
    print("django__django-11630 が見つかりません！")

