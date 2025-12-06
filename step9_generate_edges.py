#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
STEP 9 — Generate Edges (v4)

Sinh cạnh (edges) từ các file CLEAN:

- neo4j_nodes_person_clean.csv
- neo4j_nodes_university_clean.csv

Quan hệ được tạo:
- alumni_of       : Person -> University
- same_university : Person <-> Person
- parent_of       : Person -> Person
- predecessor_of  : Person -> Person
- successor_of    : Person -> Person
- spouse_of       : Person <-> Person (nếu match được)
- same_party      : Person <-> Person (nếu có dữ liệu 'party')
- same_country    : University <-> University (dùng cột 'country')

Output:
- graph_out/neo4j_edges_clean.csv
"""

import csv
from pathlib import Path
from typing import Dict, List, Tuple, Set
from utils_wiki import normalize

Edge = Tuple[str, str, str, str, str]  # (src_id, src_type, dst_id, dst_type, relation)

# -------------------------------
# Helper chung
# -------------------------------

def log(msg: str):
    print(msg)

def load_csv(path: Path) -> List[Dict[str, str]]:
    out = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(row)
    return out

def split_candidates(s: str) -> List[str]:
    """Tách 1 ô chứa nhiều tên thành list candidate."""
    if not s:
        return []
    s = normalize(s)
    # Tách theo ; hoặc , hoặc từ " và "
    parts = []
    for sep in [";", ",", " và "]:
        if sep in s:
            tmp = []
            for chunk in (parts or [s]):
                tmp.extend(chunk.split(sep))
            parts = tmp
        else:
            if not parts:
                parts = [s]
    # Normalize từng phần
    out = []
    for p in parts:
        p = normalize(p)
        if p:
            out.append(p)
    return out

def build_name_to_id_map(nodes: List[Dict[str, str]]) -> Dict[str, str]:
    m = {}
    for n in nodes:
        name = normalize(n.get("name"))
        if name:
            m[name] = n["id"]
    return m

def match_person_by_name(cand: str, persons: List[Dict[str, str]]) -> str:
    """Tìm id person gần giống với chuỗi cand (best-effort)."""
    cand_norm = normalize(cand)
    if not cand_norm:
        return ""

    # Ưu tiên khớp full name
    for p in persons:
        full = normalize(p.get("name"))
        if full == cand_norm:
            return p["id"]

    # Nếu không trùng hoàn toàn, thử 'cand in full' hoặc 'full in cand'
    for p in persons:
        full = normalize(p.get("name"))
        if not full:
            continue
        if cand_norm in full or full in cand_norm:
            return p["id"]

    return ""

def extract_uni_tokens_from_text(s: str) -> Set[str]:
    """
    Từ text Alma mater / education, rút ra các mẩu có vẻ là tên trường:
    chỉ giữ mẩu chứa 'Đại học', 'University', 'Trường'.
    """
    out: Set[str] = set()
    if not s:
        return out
    s_norm = normalize(s)
    # cắt thô theo ; và ,
    raw_parts = []
    for chunk in s_norm.split(";"):
        raw_parts.extend(chunk.split(","))

    for p in raw_parts:
        p = p.strip()
        if not p:
            continue
        if ("đại học" in p.lower()
            or "university" in p.lower()
            or "trường" in p.lower()):
            out.add(p)
    return out

def match_university_by_text(
    text: str,
    universities: List[Dict[str, str]]
) -> List[str]:
    """
    Từ Alma mater / education text, suy ra list university_id liên quan.
    Best-effort: so sánh tên trường với substring trong text.
    """
    if not text:
        return []

    text_norm = normalize(text).lower()
    uni_ids: List[str] = []

    for u in universities:
        uname = normalize(u.get("name"))
        if not uname:
            continue
        uname_low = uname.lower()
        if uname_low in text_norm or text_norm in uname_low:
            uni_ids.append(u["id"])

    # Loại trùng
    uni_ids = list(dict.fromkeys(uni_ids))
    return uni_ids

# -------------------------------
# 1) alumni_of: Person -> University
# -------------------------------

def extract_alumni_edges(
    persons: List[Dict[str, str]],
    universities: List[Dict[str, str]]
) -> List[Edge]:
    edges: List[Edge] = []

    for p in persons:
        pid = p["id"]
        alma = p.get("alma_mater", "") or ""
        edu  = p.get("education", "") or ""

        text = "; ".join([alma, edu])
        if not text.strip():
            continue

        uni_ids = match_university_by_text(text, universities)
        for uid in uni_ids:
            edges.append((pid, "Person", uid, "University", "alumni_of"))

    return edges

# -------------------------------
# 2) same_university: Person <-> Person
# -------------------------------

def extract_same_university_edges(persons: List[Dict[str, str]]) -> List[Edge]:
    # Map person_id -> set tên trường (token)
    pid_to_unis: Dict[str, Set[str]] = {}

    for p in persons:
        pid = p["id"]
        alma = p.get("alma_mater", "") or ""
        edu  = p.get("education", "") or ""
        tokens = extract_uni_tokens_from_text("; ".join([alma, edu]))
        pid_to_unis[pid] = tokens

    edges: List[Edge] = []
    n = len(persons)
    for i in range(n):
        for j in range(i + 1, n):
            pi = persons[i]["id"]
            pj = persons[j]["id"]
            si = pid_to_unis.get(pi, set())
            sj = pid_to_unis.get(pj, set())
            if not si or not sj:
                continue
            if si.intersection(sj):
                edges.append((pi, "Person", pj, "Person", "same_university"))
                edges.append((pj, "Person", pi, "Person", "same_university"))

    return edges

# -------------------------------
# 3) parent_of: Person -> Person (từ 'children')
# -------------------------------

def extract_parent_edges(persons: List[Dict[str, str]]) -> List[Edge]:
    edges: List[Edge] = []
    for p in persons:
        pid = p["id"]
        children_text = p.get("children", "") or ""
        if not children_text.strip():
            continue
        cands = split_candidates(children_text)
        for c in cands:
            cid = match_person_by_name(c, persons)
            if cid and cid != pid:
                edges.append((pid, "Person", cid, "Person", "parent_of"))
    return edges

# -------------------------------
# 4) predecessor / successor giữa Person
# -------------------------------

def extract_pre_suc_edges(persons: List[Dict[str, str]]) -> List[Edge]:
    edges: List[Edge] = []
    for p in persons:
        pid = p["id"]

        # predecessor: người giữ chức vụ trước đó
        pre_text = p.get("predecessor", "") or ""
        if pre_text.strip():
            cands = split_candidates(pre_text)
            for c in cands:
                pre_id = match_person_by_name(c, persons)
                if pre_id and pre_id != pid:
                    # predecessor_of: pre -> current
                    edges.append((pre_id, "Person", pid, "Person", "predecessor_of"))

        # successor
        suc_text = p.get("successor", "") or ""
        if suc_text.strip():
            cands = split_candidates(suc_text)
            for c in cands:
                suc_id = match_person_by_name(c, persons)
                if suc_id and suc_id != pid:
                    # successor_of: current -> suc
                    edges.append((pid, "Person", suc_id, "Person", "successor_of"))

    return edges

# -------------------------------
# 5) spouse_of giữa Person
# -------------------------------

def extract_spouse_edges(persons: List[Dict[str, str]]) -> List[Edge]:
    edges: List[Edge] = []
    for p in persons:
        pid = p["id"]
        spouse_text = p.get("spouse", "") or ""
        if not spouse_text.strip():
            continue
        cands = split_candidates(spouse_text)
        for c in cands:
            sid = match_person_by_name(c, persons)
            if sid and sid != pid:
                # cho đối xứng
                edges.append((pid, "Person", sid, "Person", "spouse_of"))
                edges.append((sid, "Person", pid, "Person", "spouse_of"))
    return edges

# -------------------------------
# 6) same_party giữa Person
# -------------------------------

def extract_same_party_edges(persons: List[Dict[str, str]]) -> List[Edge]:
    party_to_ids: Dict[str, List[str]] = {}
    for p in persons:
        pid = p["id"]
        party = normalize(p.get("party", "") or "")
        if not party:
            continue
        party_to_ids.setdefault(party, []).append(pid)

    edges: List[Edge] = []
    for party, plist in party_to_ids.items():
        if len(plist) < 2:
            continue
        for i in range(len(plist)):
            for j in range(i + 1, len(plist)):
                a, b = plist[i], plist[j]
                edges.append((a, "Person", b, "Person", "same_party"))
                edges.append((b, "Person", a, "Person", "same_party"))

    return edges

# -------------------------------
# 7) same_country giữa University
# -------------------------------

def extract_same_country_edges(universities: List[Dict[str, str]]) -> Tuple[List[Edge], int]:
    id_to_country: Dict[str, str] = {}

    for u in universities:
        uid = u["id"]
        country_raw = u.get("country", "") or ""
        country = normalize(country_raw)
        if not country:
            continue
        id_to_country[uid] = country

    log(f"[Step9] universities with detected country: {len(id_to_country)}")

    country_to_unis: Dict[str, List[str]] = {}
    for uid, c in id_to_country.items():
        country_to_unis.setdefault(c, []).append(uid)

    edges: List[Edge] = []
    for c, ulist in country_to_unis.items():
        if len(ulist) < 2:
            continue
        for i in range(len(ulist)):
            for j in range(i + 1, len(ulist)):
                a, b = ulist[i], ulist[j]
                if a == b:
                    continue
                edges.append((a, "University", b, "University", "same_country"))
                edges.append((b, "University", a, "University", "same_country"))

    return edges, len(id_to_country)

# -------------------------------
# MAIN
# -------------------------------

def main():
    root = Path("graph_out")
    person_path = root / "neo4j_nodes_person_clean.csv"
    uni_path    = root / "neo4j_nodes_university_clean.csv"

    persons      = load_csv(person_path)
    universities = load_csv(uni_path)

    log(f"[Step9] persons      : {len(persons)}")
    log(f"[Step9] universities : {len(universities)}")

    # 1) alumni_of
    alumni_edges = extract_alumni_edges(persons, universities)
    log(f"[Step9] alumni_of edges      : {len(alumni_edges)}")

    # 2) same_university
    same_uni_edges = extract_same_university_edges(persons)
    log(f"[Step9] same_university edges: {len(same_uni_edges)}")

    # 3) parent_of
    parent_edges = extract_parent_edges(persons)
    log(f"[Step9] parent_of edges      : {len(parent_edges)}")

    # 4) predecessor / successor
    pre_suc_edges = extract_pre_suc_edges(persons)
    log(f"[Step9] predecessor/successor edges: {len(pre_suc_edges)}")

    # 5) spouse_of
    spouse_edges = extract_spouse_edges(persons)
    log(f"[Step9] spouse_of edges      : {len(spouse_edges)}")

    # 6) same_party
    same_party_edges = extract_same_party_edges(persons)
    log(f"[Step9] same_party edges     : {len(same_party_edges)}")

    # 7) same_country
    same_country_edges, n_country = extract_same_country_edges(universities)
    log(f"[Step9] same_country edges   : {len(same_country_edges)}")

    # Gom tất cả edges, bỏ trùng
    all_edges: List[Edge] = []
    all_edges.extend(alumni_edges)
    all_edges.extend(same_uni_edges)
    all_edges.extend(parent_edges)
    all_edges.extend(pre_suc_edges)
    all_edges.extend(spouse_edges)
    all_edges.extend(same_party_edges)
    all_edges.extend(same_country_edges)

    # Deduplicate
    unique_edges = list(dict.fromkeys(all_edges))
    log(f"[Step9] Write {len(unique_edges)} unique edges -> {root / 'neo4j_edges_clean.csv'}")

    out_path = root / "neo4j_edges_clean.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["src_id", "src_type", "dst_id", "dst_type", "relation"])
        for e in unique_edges:
            writer.writerow(e)

    log("[Step9] DONE.")

if __name__ == "__main__":
    main()
