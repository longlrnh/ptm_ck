# -*- coding: utf-8 -*-
"""
step6_export_neo4j.py
- Đọc các file cuối trong graph_out/
- Gán ID số cho Person / University
- Sinh các file nodes_* và rel_* với tên cột rõ ràng, dễ dùng trong Neo4j:

  NODES:
    - neo4j_nodes_person.csv
    - neo4j_nodes_university.csv

  RELS:
    - neo4j_rel_alumni_of.csv
    - neo4j_rel_shared_university.csv
    - neo4j_rel_person_mentions_person.csv
    - neo4j_rel_person_mentions_university.csv
    - neo4j_rel_university_mentions_person.csv
    - neo4j_rel_university_mentions_university.csv
"""

import os
import csv
import json
import argparse
from urllib.parse import quote


DEFAULT_OUTDIR = "graph_out"


def wiki_link(title: str) -> str:
    title = (title or "").replace(" ", "_")
    return f"https://vi.wikipedia.org/wiki/{quote(title)}"


def load_node_details(path):
    if not os.path.exists(path):
        raise SystemExit(f"[ERROR] Không tìm thấy node_details.json tại: {path}. Hãy chạy Step 4 trước.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def build_initial_id_maps(node_details):
    """
    Tạo ID ban đầu từ node_details.json (nếu có).
    Trả về:
      - person_id: dict[title] -> int
      - uni_id: dict[title] -> int
      - person_rows: list[dict]
      - uni_rows: list[dict]
    """
    person_id = {}
    uni_id = {}
    person_rows = []
    uni_rows = []
    pid = 1
    uid = 1

    for nd in node_details:
        title = nd.get("title")
        ntype = nd.get("type")
        link = nd.get("link") or ""
        if not title or not ntype:
            continue

        if ntype == "person":
            if title not in person_id:
                person_id[title] = pid
                person_rows.append({
                    "id": pid,
                    "name": title,
                    "label": "Person",
                    "wiki_url": link or wiki_link(title),
                })
                pid += 1
        elif ntype == "university":
            if title not in uni_id:
                uni_id[title] = uid
                uni_rows.append({
                    "id": uid,
                    "name": title,
                    "label": "University",
                    "wiki_url": link or wiki_link(title),
                })
                uid += 1

    return person_id, uni_id, person_rows, uni_rows, pid, uid


def main():
    ap = argparse.ArgumentParser(description="Step 6 — Export dữ liệu dạng Neo4j-friendly.")
    ap.add_argument(
        "--outdir",
        default=DEFAULT_OUTDIR,
        help="Thư mục graph_out (chứa edges_*.csv, node_details.json)",
    )
    args = ap.parse_args()

    odir = args.outdir
    if not os.path.isdir(odir):
        raise SystemExit(f"[ERROR] Thư mục outdir không tồn tại: {odir}")

    node_details_path = os.path.join(odir, "node_details.json")
    node_details = load_node_details(node_details_path)

    # 1) ID ban đầu từ node_details.json
    (
        person_id,
        uni_id,
        person_rows,
        uni_rows,
        next_pid,
        next_uid,
    ) = build_initial_id_maps(node_details)

    # ---- Helper để đảm bảo mọi node trong cạnh đều có ID ----
    def ensure_person(title: str):
        nonlocal next_pid
        title = (title or "").strip()
        if not title:
            return None
        if title not in person_id:
            person_id[title] = next_pid
            person_rows.append({
                "id": next_pid,
                "name": title,
                "label": "Person",
                "wiki_url": wiki_link(title),
            })
            next_pid += 1
        return person_id[title]

    def ensure_university(title: str):
        nonlocal next_uid
        title = (title or "").strip()
        if not title:
            return None
        if title not in uni_id:
            uni_id[title] = next_uid
            uni_rows.append({
                "id": next_uid,
                "name": title,
                "label": "University",
                "wiki_url": wiki_link(title),
            })
            next_uid += 1
        return uni_id[title]

    # 2) Đọc 6 file cạnh và sinh file rel_*
    rel_alumni = []
    rel_shared = []
    rel_pp = []
    rel_pu = []
    rel_up = []
    rel_uu = []

    # ---------- ALUMNI_OF ----------
    path_alumni = os.path.join(odir, "edges_alumni_pu.csv")
    if os.path.exists(path_alumni):
        with open(path_alumni, "r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                p = (r.get("src_person") or "").strip()
                u = (r.get("dst_university") or "").strip()
                year = (r.get("year") or "").strip()
                pid = ensure_person(p)
                uid = ensure_university(u)
                if pid is None or uid is None:
                    continue
                rel_alumni.append({
                    "src_person_id": pid,
                    "dst_university_id": uid,
                    "src_person": p,
                    "dst_university": u,
                    "year": year,
                })

    # ---------- SHARED_UNI ----------
    path_shared = os.path.join(odir, "edges_shared_uni_pp.csv")
    if os.path.exists(path_shared):
        with open(path_shared, "r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                p1 = (r.get("src_person") or "").strip()
                p2 = (r.get("dst_person") or "").strip()
                cnt = (r.get("count") or "").strip()
                id1 = ensure_person(p1)
                id2 = ensure_person(p2)
                if id1 is None or id2 is None:
                    continue
                rel_shared.append({
                    "src_person_id": id1,
                    "dst_person_id": id2,
                    "src_person": p1,
                    "dst_person": p2,
                    "shared_count": cnt,
                })

    # ---------- mentions: PERSON -> PERSON ----------
    path_pp = os.path.join(odir, "edges_mentions_pp.csv")
    if os.path.exists(path_pp):
        with open(path_pp, "r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                s = (r.get("src_person") or "").strip()
                d = (r.get("dst_person") or "").strip()
                id_s = ensure_person(s)
                id_d = ensure_person(d)
                if id_s is None or id_d is None:
                    continue
                rel_pp.append({
                    "src_person_id": id_s,
                    "dst_person_id": id_d,
                    "src_person": s,
                    "dst_person": d,
                })

    # ---------- mentions: PERSON -> UNIVERSITY ----------
    path_pu = os.path.join(odir, "edges_mentions_pu.csv")
    if os.path.exists(path_pu):
        with open(path_pu, "r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                s = (r.get("src_person") or "").strip()
                d = (r.get("dst_university") or "").strip()
                id_s = ensure_person(s)
                id_d = ensure_university(d)
                if id_s is None or id_d is None:
                    continue
                rel_pu.append({
                    "src_person_id": id_s,
                    "dst_university_id": id_d,
                    "src_person": s,
                    "dst_university": d,
                })

    # ---------- mentions: UNIVERSITY -> PERSON ----------
    path_up = os.path.join(odir, "edges_uni_mentions_p.csv")
    if os.path.exists(path_up):
        with open(path_up, "r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                s = (r.get("src_university") or "").strip()
                d = (r.get("dst_person") or "").strip()
                id_s = ensure_university(s)
                id_d = ensure_person(d)
                if id_s is None or id_d is None:
                    continue
                rel_up.append({
                    "src_university_id": id_s,
                    "dst_person_id": id_d,
                    "src_university": s,
                    "dst_person": d,
                })

    # ---------- mentions: UNIVERSITY -> UNIVERSITY ----------
    path_uu = os.path.join(odir, "edges_uni_mentions_u.csv")
    if os.path.exists(path_uu):
        with open(path_uu, "r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                s = (r.get("src_university") or "").strip()
                d = (r.get("dst_university") or "").strip()
                id_s = ensure_university(s)
                id_d = ensure_university(d)
                if id_s is None or id_d is None:
                    continue
                rel_uu.append({
                    "src_university_id": id_s,
                    "dst_university_id": id_d,
                    "src_university": s,
                    "dst_university": d,
                })

    # 3) Ghi file nodes_*
    nodes_person_path = os.path.join(odir, "neo4j_nodes_person.csv")
    nodes_univ_path = os.path.join(odir, "neo4j_nodes_university.csv")

    write_csv(
        nodes_person_path,
        ["id", "name", "label", "wiki_url"],
        person_rows,
    )
    write_csv(
        nodes_univ_path,
        ["id", "name", "label", "wiki_url"],
        uni_rows,
    )

    # 4) Ghi file rel_*
    write_csv(
        os.path.join(odir, "neo4j_rel_alumni_of.csv"),
        ["src_person_id", "dst_university_id", "src_person", "dst_university", "year"],
        rel_alumni,
    )
    write_csv(
        os.path.join(odir, "neo4j_rel_shared_university.csv"),
        ["src_person_id", "dst_person_id", "src_person", "dst_person", "shared_count"],
        rel_shared,
    )
    write_csv(
        os.path.join(odir, "neo4j_rel_person_mentions_person.csv"),
        ["src_person_id", "dst_person_id", "src_person", "dst_person"],
        rel_pp,
    )
    write_csv(
        os.path.join(odir, "neo4j_rel_person_mentions_university.csv"),
        ["src_person_id", "dst_university_id", "src_person", "dst_university"],
        rel_pu,
    )
    write_csv(
        os.path.join(odir, "neo4j_rel_university_mentions_person.csv"),
        ["src_university_id", "dst_person_id", "src_university", "dst_person"],
        rel_up,
    )
    write_csv(
        os.path.join(odir, "neo4j_rel_university_mentions_university.csv"),
        ["src_university_id", "dst_university_id", "src_university", "dst_university"],
        rel_uu,
    )

    # 5) In summary
    print("\n✅ Step 6 — Export Neo4j files DONE")
    print(f"  Persons           : {len(person_rows)}")
    print(f"  Universities      : {len(uni_rows)}")
    print(f"  ALUMNI_OF         : {len(rel_alumni)}")
    print(f"  SHARED_UNI        : {len(rel_shared)}")
    print(f"  P->P MENTIONS     : {len(rel_pp)}")
    print(f"  P->U MENTIONS     : {len(rel_pu)}")
    print(f"  U->P MENTIONS     : {len(rel_up)}")
    print(f"  U->U MENTIONS     : {len(rel_uu)}")
    print(f"\n  Files written in: {odir}/")
    print("    - neo4j_nodes_person.csv")
    print("    - neo4j_nodes_university.csv")
    print("    - neo4j_rel_alumni_of.csv")
    print("    - neo4j_rel_shared_university.csv")
    print("    - neo4j_rel_person_mentions_person.csv")
    print("    - neo4j_rel_person_mentions_university.csv")
    print("    - neo4j_rel_university_mentions_person.csv")
    print("    - neo4j_rel_university_mentions_university.csv")


if __name__ == "__main__":
    main()
