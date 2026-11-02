import json

with open("config/sources.json", "r", encoding="utf-8") as f:
    s = json.load(f)

sources = s.get("sources", [])
print("Source count:", len(sources))
for item in sources[:3]:
    print(item)
# Also check for rekrute_com
for item in sources:
    if "rekrute" in item.get("code", ""):
        print("Found rekrute:", item)
