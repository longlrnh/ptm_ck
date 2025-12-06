# debug_node_details.py
import sys
import json
from pathlib import Path

# Ép stdout dùng UTF-8 để tránh UnicodeEncodeError trên Windows
sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent
json_path = BASE_DIR / "graph_out" / "node_details.json"

print("Đang đọc file:", json_path)

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

print("Tổng record:", len(data))
print("Kiểu data:", type(data))

print("\n=== 3 record đầu tiên ===")
for item in data[:3]:
    print("----")
    print("title:", item.get("title"))
    print("type :", item.get("type"))
    print("link :", item.get("link"))
