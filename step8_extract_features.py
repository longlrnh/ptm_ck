#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
STEP 8 — Extract Features (v3):
Tạo 3 loại output cho mỗi node type (person / university):
1) *_enriched.csv — các thuộc tính được flatten từ infobox
2) *_props.csv — debug (tất cả props dạng JSON)
3) *_clean.csv — bản RÚT GỌN cho Neo4j + báo cáo cuối kì
"""

import re
import csv
import json
from pathlib import Path
from typing import Dict, Any, List
from utils_wiki import normalize

# Logger đơn giản
def log(msg: str):
    print(msg)

def load_csv(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(row)
    return out

def has_letter(s: str) -> bool:
    return any(ch.isalpha() for ch in s)

# ======================================================================
# 1. Mapping key RAW (infobox) → key CLEAN schema
# ======================================================================

PERSON_CLEAN_MAP = {
    "Sinh": "birth_date",
    "Nơi sinh": "birth_place",
    "Mất": "death_date",
    "Đảng phái": "party",
    "Đảng": "party",
    "Chức vụ": "office",
    "Chức vụ chính": "office",
    "Nghề nghiệp": "occupation",
    "Học vấn": "education",
    "Alma mater": "alma_mater",
    "Vợ chồng": "spouse",
    "Vợ/chồng": "spouse",
    "Con cái": "children",
    "Quốc tịch": "nationality",
}

UNIVERSITY_CLEAN_MAP = {
    "Loại hình": "type",
    "Loại": "type",

    "Thành lập": "founded",
    "Thành lập / mở cửa": "founded",
    "Founded": "founded",

    # country – nếu infobox có sẵn
    "Quốc gia": "country",
    "Quốc gia / vùng": "country",
    "Quốc gia/vùng": "country",
    "Quốc gia hoặc vùng": "country",
    "Country": "country",

    # city / location
    "Thành phố": "city",
    "Thành phố/tỉnh": "city",
    "Thành phố / Tỉnh": "city",
    "Thành phố / tỉnh": "city",
    "Vị trí": "city",
    "Địa điểm": "city",
    "Location": "city",

    # students
    "Sinh viên": "students",
    "Sinh viên (2023)": "students",
    "Sinh viên (2022)": "students",
    "Số sinh viên": "students",
    "Students": "students",

    # website
    "Trang web": "website",
    "Trang Web": "website",
    "Website": "website",

    # motto
    "Khẩu hiệu": "motto",
    "Châm ngôn": "motto",
    "Motto": "motto",
}

# ======================================================================
# Helper
# ======================================================================

def flatten_value(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return "; ".join(str(x).strip() for x in v if str(x).strip())
    return str(v).strip()

def parse_location_to_city_country(text: str):
    """
    Nhận chuỗi kiểu:
      'Thành phố New York, Hoa Kỳ'
      'Hamburg , Đức'
      'Austin; ,; Texas; ,; Hoa Kỳ; ...'
    Trả về (city, country)
    """
    if not text:
        return None, None

    # chuẩn hoá khoảng trắng và ; , 
    t = normalize(text)
    # cắt theo dấu phẩy
    parts = [p.strip(" ;") for p in t.split(",") if p.strip(" ;")]
    if len(parts) < 2:
        return None, None

    # country = phần cuối, city = phần đầu
    country = parts[-1]
    city = parts[0]
    return city, country

def derive_country_from_city(text: str) -> str:
    """
    Suy country từ chuỗi 'city', loại bỏ:
    - đoạn có số (toạ độ, năm)
    - đoạn quá ngắn hoặc chỉ có ký tự / , ; ...
    - đoạn kiểu 'Bản mẫu:Official url'
    Ví dụ:
        "Baltimore; ,; Maryland; ,; Hoa Kỳ; 39°...; ﻿ /"
    -> 'Hoa Kỳ'
    """
    if not text:
        return ""
    s = normalize(text)

    # tách theo ; hoặc ,
    parts = re.split(r"[;,]", s)

    candidates = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # bỏ các đoạn có số (thường là toạ độ, năm)
        if any(ch.isdigit() for ch in p):
            continue
        # bỏ các đoạn rất ngắn hoặc không có chữ cái (chỉ là /, dấu cách, ký hiệu)
        if len(p) < 3 or not has_letter(p):
            continue
        # bỏ mấy đoạn kiểu "Bản mẫu:Official url"
        if p.lower().startswith("bản mẫu"):
            continue
        candidates.append(p)

    if not candidates:
        return ""

    # duyệt từ cuối lên (thường country nằm cuối)
    for p in reversed(candidates):
        return p

    # fallback (thực ra không tới đây)
    return candidates[-1]

# ======================================================================
# Helper chọn subset thuộc tính CLEAN
# ======================================================================

def pick_clean_fields(props: Dict[str, Any], label: str) -> Dict[str, Any]:
    out = {}
    mapping = PERSON_CLEAN_MAP if label == "person" else UNIVERSITY_CLEAN_MAP

    if label == "university":
        # 1) xử lý đặc biệt ô "Vị trí" -> city & country
        loc_raw = props.get("Vị trí") or props.get("Vị trí ")
        if loc_raw:
            city, country = parse_location_to_city_country(flatten_value(loc_raw))
            if city:
                out["city"] = city
            if country:
                out["country"] = country

    # 2) xử lý các key còn lại theo mapping chuẩn
    for raw_key, clean_key in mapping.items():
        if raw_key not in props:
            continue
        v = props[raw_key]
        if isinstance(v, list):
            v = "; ".join(str(x).strip() for x in v if str(x).strip())

        # tránh ghi đè city/country nếu đã set từ "Vị trí"
        if label == "university" and clean_key in ("city", "country") and clean_key in out:
            continue

        out[clean_key] = v

    return out

# ======================================================================
# ENRICHED + PROPS output
# ======================================================================

def write_enriched_csv(label: str,
                       nodes: List[Dict[str, str]],
                       matched_details: Dict[str, Dict[str, Any]],
                       prop_keys: List[str],
                       out_path: Path):

    base_fields = ["id", "name", "label", "wiki_url"]
    fieldnames = base_fields + prop_keys
    log(f"[Step8] Write enriched: {out_path}")

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for n in nodes:
            nid = n.get("id")
            row = {
                "id": nid,
                "name": n.get("name"),
                "label": n.get("label"),
                "wiki_url": n.get("wiki_url"),
            }

            d = matched_details.get(nid)
            if d is None:
                for k in prop_keys:
                    row[k] = ""
            else:
                props = d.get("properties", d)
                for k in prop_keys:
                    row[k] = flatten_value(props.get(k, ""))

            writer.writerow(row)


def write_props_csv(label: str,
                    nodes: List[Dict[str, str]],
                    matched_details: Dict[str, Dict[str, Any]],
                    out_path: Path):

    log(f"[Step8] Write props debug: {out_path}")
    with out_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = ["id", "name", "label", "wiki_url", "properties"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for n in nodes:
            nid = n.get("id")
            props = matched_details.get(nid)
            if props is not None:
                props = props.get("properties", props)
            writer.writerow({
                "id": nid,
                "name": n.get("name"),
                "label": n.get("label"),
                "wiki_url": n.get("wiki_url"),
                "properties": json.dumps(props, ensure_ascii=False),
            })


# ======================================================================
# CLEAN output — schema rút gọn
# ======================================================================

def write_clean_nodes_csv(label: str,
                          nodes: List[Dict[str, str]],
                          matched_details: Dict[str, Dict[str, Any]],
                          out_path: Path):

    base_fields = ["id", "name", "label", "wiki_url"]

    mapping = PERSON_CLEAN_MAP if label == "person" else UNIVERSITY_CLEAN_MAP

    clean_keys = set()
    for d in matched_details.values():
        props = d.get("properties", d)
        clean = pick_clean_fields(props, label)
        for ck in clean.keys():
            clean_keys.add(ck)

    clean_fields = sorted(clean_keys)
    fieldnames = base_fields + clean_fields

    log(f"[Step8] Write CLEAN CSV: {out_path}")
    log(f"[Step8] Extra fields: {clean_fields}")

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for n in nodes:
            nid = n.get("id")
            row = {
                "id": nid,
                "name": n.get("name"),
                "label": n.get("label"),
                "wiki_url": n.get("wiki_url"),
            }

            d = matched_details.get(nid)
            if d is None:
                for k in clean_fields:
                    row[k] = ""
            else:
                props = d.get("properties", d)
                clean = pick_clean_fields(props, label)
                for k in clean_fields:
                    row[k] = flatten_value(clean.get(k, ""))

            writer.writerow(row)


# ======================================================================
# MAIN
# ======================================================================

def process_node_type(
    label: str,
    node_csv_path: Path,
    node_details: List[Dict[str, Any]],
    out_dir: Path
):
    log(f"\n[Step8] === PROCESS: {label} ===")

    nodes = load_csv(node_csv_path)
    log(f"[Step8] Nodes count = {len(nodes)}")

    by_title = {d["title"]: d for d in node_details}
    by_link  = {d["link"]: d for d in node_details}

    def match_detail(row):
        link = row.get("wiki_url")
        if link in by_link:
            return by_link[link]
        title = row.get("name")
        return by_title.get(title)

    matched = {}
    for n in nodes:
        nid = n["id"]
        d = match_detail(n)
        if d:
            matched[nid] = d

    log(f"[Step8] Matched {len(matched)} / {len(nodes)} nodes.")

    all_prop_keys = set()
    for d in matched.values():
        props = d.get("properties", d)
        for k in props.keys():
            all_prop_keys.add(k)
    all_prop_keys = sorted(all_prop_keys)

    write_enriched_csv(
        label, nodes, matched, all_prop_keys,
        out_dir / f"neo4j_nodes_{label}_enriched.csv"
    )

    write_props_csv(
        label, nodes, matched,
        out_dir / f"neo4j_nodes_{label}_props.csv"
    )

    write_clean_nodes_csv(
        label, nodes, matched,
        out_dir / f"neo4j_nodes_{label}_clean.csv"
    )


def main():
    root = Path("graph_out")
    details_path = root / "node_details.json"

    node_details = json.loads(details_path.read_text(encoding="utf-8"))

    process_node_type("person",     root / "neo4j_nodes_person.csv",     node_details, root)
    process_node_type("university", root / "neo4j_nodes_university.csv", node_details, root)

    log("\n[Step8] DONE.")


if __name__ == "__main__":
    main()
