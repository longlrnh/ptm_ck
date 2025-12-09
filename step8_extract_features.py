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

def has_university(props: Dict[str, Any]) -> bool:
    """
    Kiểm tra xem properties có chứa ít nhất 1 trường đại học (Alma mater) không
    """
    alma_mater = props.get("Alma mater")
    if not alma_mater:
        return False
    
    # Nếu là list, kiểm tra có phần tử nào là tên trường đại học thực sự không
    if isinstance(alma_mater, list):
        # Loại bỏ các phần tử chỉ là ký tự đặc biệt hoặc số đơn lẻ
        valid_items = []
        for x in alma_mater:
            s = str(x).strip()
            # Bỏ qua các ký tự đặc biệt và số đơn lẻ
            if s and s not in ["[", "]", "(", ")", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]:
                # Kiểm tra có chứa chữ cái (tên trường đại học thường có chữ cái)
                if has_letter(s) and len(s) > 2:
                    valid_items.append(s)
        return len(valid_items) > 0
    
    # Nếu là string, kiểm tra không rỗng và có chữ cái
    s = str(alma_mater).strip()
    return bool(s) and has_letter(s) and len(s) > 2

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
    "Giáo dục": "education",
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
# Helper để xuất CSV cho career và country
# ======================================================================

def write_filtered_nodes_csv(label: str,
                             nodes: List[Dict[str, str]],
                             matched_details: Dict[str, Dict[str, Any]],
                             filter_field: str,
                             filter_raw_key: str,
                             out_path: Path):
    """
    Xuất CSV cho các nodes có trường filter_field (career hoặc country)
    filter_field: "career" hoặc "country"
    filter_raw_key: key trong properties (ví dụ "Nghề nghiệp" hoặc "Quốc tịch")
    """
    base_fields = ["id", "name", "label", "wiki_url", filter_field]
    log(f"[Step8] Write filtered CSV ({filter_field}): {out_path}")
    
    filtered_nodes = []
    for n in nodes:
        nid = n.get("id")
        d = matched_details.get(nid)
        if d is None:
            continue
        
        props = d.get("properties", d)
        filter_value = props.get(filter_raw_key)
        
        if filter_value:
            # Kiểm tra giá trị không rỗng
            if isinstance(filter_value, list):
                clean_values = [str(x).strip() for x in filter_value if str(x).strip()]
                if clean_values:
                    filtered_nodes.append({
                        "id": nid,
                        "name": n.get("name"),
                        "label": n.get("label"),
                        "wiki_url": n.get("wiki_url"),
                        filter_field: flatten_value(filter_value)
                    })
            elif str(filter_value).strip():
                filtered_nodes.append({
                    "id": nid,
                    "name": n.get("name"),
                    "label": n.get("label"),
                    "wiki_url": n.get("wiki_url"),
                    filter_field: flatten_value(filter_value)
                })
    
    log(f"[Step8] Found {len(filtered_nodes)} nodes with {filter_field}")
    
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=base_fields)
        writer.writeheader()
        writer.writerows(filtered_nodes)

# ======================================================================
# CLEAN output — schema rút gọn
# ======================================================================

def write_clean_nodes_csv(label: str,
                          nodes: List[Dict[str, str]],
                          matched_details: Dict[str, Dict[str, Any]],
                          out_path: Path,
                          filter_university: bool = False):

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
    
    if filter_university:
        log(f"[Step8] Filtering: only nodes with at least 1 university")

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        filtered_count = 0
        total_count = 0
        for n in nodes:
            nid = n.get("id")
            total_count += 1
            
            # Nếu filter_university=True và label="person", chỉ giữ nodes có university
            if filter_university and label == "person":
                d = matched_details.get(nid)
                if d is None:
                    continue
                props = d.get("properties", d)
                if not has_university(props):
                    continue
                filtered_count += 1
            
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
        
        if filter_university:
            log(f"[Step8] Filtered: {filtered_count} / {total_count} nodes have universities")


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

    # Cho person nodes: filter để chỉ giữ những node có ít nhất 1 university
    filter_uni = (label == "person")
    write_clean_nodes_csv(
        label, nodes, matched,
        out_dir / f"neo4j_nodes_{label}_clean.csv",
        filter_university=filter_uni
    )
    
    # Xuất các file CSV riêng cho career và country (chỉ cho person)
    if label == "person":
        write_filtered_nodes_csv(
            label, nodes, matched,
            "career", "Nghề nghiệp",
            out_dir / "neo4j_nodes_person_career.csv"
        )
        write_filtered_nodes_csv(
            label, nodes, matched,
            "country", "Quốc tịch",
            out_dir / "neo4j_nodes_person_country.csv"
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
