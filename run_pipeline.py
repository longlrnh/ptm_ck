# -*- coding: utf-8 -*-
"""
run_pipeline.py
- Step 1: Crawl links/info cho ROOTS (append nếu thiếu)
- Step 2: Build seeds/edges multi-root (ép chạy lại nếu cần)
- Step 3: BFS mở rộng
- Step 4: Enrich + export node_details & edges (KHÔNG LINKS_TO)
- Step 5: Clean output — tập kết quả cuối cùng (edges, node details, graph.json, node props)
- Step 6: Export thêm các file nodes/relationships dạng Neo4j-friendly (neo4j_nodes_*, neo4j_rel_*)
"""

import os, sys, subprocess, json, tempfile, shutil
import pandas as pd
from utils_wiki import normalize

# =============================
# ===== GLOBAL CONFIG =========
# =============================
OUT = "graph_out"
ROOTS = [
  # People
  "Mark Zuckerberg"
  # Universities
]

FORCE_CLEAN = True      # Xóa sạch graph_out mỗi lần chạy
FORCE_STEP2 = True      # (giữ biến cho hợp thức, không chèn flag --force vì step2 không hỗ trợ)

# (Tuỳ chọn) thông số Step 4
STEP4_WORKERS = os.cpu_count() or 8
STEP4_SLEEP   = "0.06"
STEP4_TIMEOUT = "6.0"

# Chỉ giữ lại các file này sau Step 5
KEEP_FILES = {
    # edges gốc
    "edges_alumni_pu.csv",
    "edges_mentions_pp.csv",
    "edges_mentions_pu.csv",
    "edges_shared_uni_pp.csv",
    "edges_uni_mentions_p.csv",
    "edges_uni_mentions_u.csv",
    # graph + node details
    "graph.json",
    "node_details.csv",
    "node_details.json",
    # node props (infobox JSON, phục vụ enrich sau này)
    "nodes_persons_props.csv",
    "nodes_universities_props.csv",
    # === Neo4j-friendly files (Step 6) ===
    "neo4j_nodes_person.csv",
    "neo4j_nodes_university.csv",
    "neo4j_rel_alumni_of.csv",
    "neo4j_rel_shared_university.csv",
    "neo4j_rel_person_mentions_person.csv",
    "neo4j_rel_person_mentions_university.csv",
    "neo4j_rel_university_mentions_person.csv",
    "neo4j_rel_university_mentions_university.csv",
}

# =============================
# ====== ENV SETTINGS =========
# =============================
ENV = os.environ.copy()
ENV["PYTHONUNBUFFERED"] = "1"

def slug(s: str):
    import re
    s = re.sub(r"\s+", "_", s.strip())
    return re.sub(r"[^\w\-\.]", "", s, flags=re.UNICODE)

def load_links_df():
    fp = os.path.join(OUT, "links.csv")
    if os.path.exists(fp):
        try:
            return pd.read_csv(fp)
        except Exception:
            return pd.DataFrame(columns=["source_title","target_title"])
    return pd.DataFrame(columns=["source_title","target_title"])

def load_info_list():
    fp = os.path.join(OUT, "info.json")
    if os.path.exists(fp):
        try:
            data = json.load(open(fp, encoding="utf-8"))
            if isinstance(data, list): return data
            if isinstance(data, dict): return [data]
        except Exception:
            pass
    return []

def info_has_root(info_list, norm_title):
    for it in info_list:
        if normalize(it.get("title","")) == norm_title:
            return True
    return False

def safe_concat(lst, cols):
    return (pd.concat(lst, ignore_index=True) if lst else pd.DataFrame(columns=cols)).drop_duplicates()

def run_cmd(cmd, desc=None):
    if desc:
        print(desc)
    print("  $", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True, env=ENV)

# =============================
# ====== START PIPELINE =======
# =============================

print("=== CLEAN PIPELINE: Step1 → Step2 → Step3 → Step4 → Step5 → Step6 ===")

# 🧹 CLEAN OUTPUT
if FORCE_CLEAN and os.path.exists(OUT):
    print(f"\n🧹 Xóa sạch thư mục {OUT}/ để chạy lại từ đầu ...")
    shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)

# ---------- PHASE 1 ----------
print("\n[PHASE 1/6] Step 1 — Crawl links & info (append nếu thiếu)")

links_df = load_links_df()
info_list = load_info_list()

for i, title in enumerate(ROOTS, 1):
    norm = normalize(title)
    has_links = False
    if not links_df.empty and "source_title" in links_df.columns:
        has_links = (links_df["source_title"].map(str) == norm).any()
    has_info = info_has_root(info_list, norm)
    if has_links and has_info:
        print(f"  [{i}/{len(ROOTS)}] ⏭️ Skip: '{title}' đã có trong links.csv & info.json")
        continue

    print(f"  [{i}/{len(ROOTS)}] step1: {title} (crawl + append)")
    run_cmd(
        [sys.executable, "-u", "step1_single_node_links.py", "--title", title, "--outdir", OUT]
    )
    links_df = load_links_df()
    info_list = load_info_list()

print(f"  ✓ links.csv rows = {links_df.shape[0]} | info.json roots = {len(info_list)}")

# ---------- PHASE 2 ----------
print("\n[PHASE 2/6] Step 2 — Build seeds & edges (multi-root)")

all_seeds = []
all_person_edges = []
all_edu_edges = []
all_root_nodes = []

for i, title in enumerate(ROOTS, 1):
    norm = normalize(title)
    root_links = links_df[links_df["source_title"].map(str) == norm]
    if root_links.empty:
        print(f"  [{i}/{len(ROOTS)}] ⚠️ Không có links cho '{title}' → bỏ qua Step2")
        continue

    tmpdir = tempfile.mkdtemp(prefix=f"_tmp_{slug(title)}_", dir=OUT)
    tmp_links_fp = os.path.join(tmpdir, "links.csv")
    root_links.to_csv(tmp_links_fp, index=False, encoding="utf-8")

    is_uni = any(k.lower() in title.lower() for k in ["đại học","university","học viện","institute","college"])
    print(f"  [{i}/{len(ROOTS)}] Step2: {title} → {'UNI' if is_uni else 'PERSON'}")

    args2 = [sys.executable, "-u", "step2_build_seeds.py",
             "--links-csv", tmp_links_fp, "--outdir", tmpdir, "--dedupe"]
    if is_uni:
        args2 += ["--assume-university"]
    else:
        args2 += ["--include-root-seed"]

    # Không chèn --force vì step2_build_seeds.py không hỗ trợ và không cần thiết
    run_cmd(args2 + ["--progress-every", "50"])

    for fn in ("seeds.csv", "person_edges.csv", "edu_edges.csv", "root_nodes.csv"):
        fp = os.path.join(tmpdir, fn)
        if os.path.exists(fp):
            df = pd.read_csv(fp)
            if fn == "seeds.csv": all_seeds.append(df)
            elif fn == "person_edges.csv": all_person_edges.append(df)
            elif fn == "edu_edges.csv": all_edu_edges.append(df)
            elif fn == "root_nodes.csv": all_root_nodes.append(df)

    shutil.rmtree(tmpdir, ignore_errors=True)

# gộp & ghi
seeds_df = safe_concat(all_seeds, ["person_title"])
person_edges_df = safe_concat(all_person_edges, ["src_root","dst_person","relation"])
edu_edges_df = safe_concat(all_edu_edges, ["src_university","dst_person","relation","year"])
root_nodes_df = safe_concat(all_root_nodes, ["title","type"])

seeds_fp = os.path.join(OUT, "seeds.csv")
person_edges_fp = os.path.join(OUT, "person_edges.csv")
edu_edges_fp = os.path.join(OUT, "edu_edges.csv")
root_nodes_fp = os.path.join(OUT, "root_nodes.csv")

seeds_df.to_csv(seeds_fp, index=False, encoding="utf-8")
person_edges_df.to_csv(person_edges_fp, index=False, encoding="utf-8")
edu_edges_df.to_csv(edu_edges_fp, index=False, encoding="utf-8")
root_nodes_df.to_csv(root_nodes_fp, index=False, encoding="utf-8")

print(f"  ✓ seeds={len(seeds_df)} | person_edges={len(person_edges_df)} | edu_edges={len(edu_edges_df)} | roots={len(root_nodes_df)}")

# rescue nếu seeds trống
if seeds_df.empty and not person_edges_df.empty:
    dst = (person_edges_df.loc[person_edges_df["relation"]=="LINK_FROM_START","dst_person"]
           .dropna().drop_duplicates())
    if not dst.empty:
        pd.DataFrame({"person_title": dst}).to_csv(seeds_fp, index=False, encoding="utf-8")
        print(f"  🔁 rescued seeds.csv from person_edges: {len(dst)} rows")

# rescue root_nodes nếu thiếu
if root_nodes_df.empty:
    rows = []
    for info in load_info_list():
        t = info.get("title")
        if not t: continue
        tl = t.lower()
        ty = "university" if any(k in tl for k in ["đại học","university","học viện","institute","college"]) else "person"
        rows.append((t, ty))
    if rows:
        pd.DataFrame(rows, columns=["title","type"]).to_csv(root_nodes_fp, index=False, encoding="utf-8")
        print(f"  🔁 rescued root_nodes.csv with {len(rows)} rows")

# ---------- PHASE 3 ----------
print("\n[PHASE 3/6] Step 3 — BFS mở rộng → graph_out/")

step3_cmd = [
    sys.executable, "-u", "step3_bfs_expand.py",
    "--seeds", os.path.join(OUT, "seeds.csv"),
    "--config", "config_example.json",
    "--outdir", OUT,
    "--checkpoint-every", "500",
    "--flush-every", "500",
    "--roots-csv", os.path.join(OUT, "root_nodes.csv"),
    "--expand-from-university",
    "--uni-candidate-cap", "200",
    "--info-json", os.path.join(OUT, "info.json"),
]
run_cmd(step3_cmd, desc=None)

print("\n  ✓ Step 3 hoàn tất")

# ---------- PHASE 4 ----------
print("\n[PHASE 4/6] Step 4 — Enrich + export node_details & edges (no LINKS_TO)")

step4_cmd = [
    sys.executable, "-u", "step4_enrich_full.py",
    "--outdir", OUT,
    "--workers", str(STEP4_WORKERS),
    "--sleep", STEP4_SLEEP,
    "--http-timeout", STEP4_TIMEOUT,
    # nếu cần giới hạn để test, thêm:
    # "--limit-persons","xxx","--limit-universities","xxx"
]
run_cmd(step4_cmd)

print("  ✓ Step 4 đã xuất:")
for fn in [
    "edges_alumni_pu.csv",
    "edges_mentions_pp.csv", "edges_mentions_pu.csv",
    "edges_shared_uni_pp.csv", "edges_uni_mentions_p.csv", "edges_uni_mentions_u.csv",
    "node_details.csv", "node_details.json",
    "nodes_persons_props.csv", "nodes_universities_props.csv",
]:
    p = os.path.join(OUT, fn)
    print(f"    - {fn} {'(OK)' if os.path.exists(p) else '(MISSING!)'}")

# ---------- PHASE 5 ----------
print("\n[PHASE 5/6] Step 5 — Clean output — chỉ giữ file cần thiết để import / phân tích")

run_cmd([sys.executable, "-u", "step5_clean.py", "--outdir", OUT])

# ---------- PHASE 6 ----------
print("\n[PHASE 6/6] Step 6 — Export Neo4j-friendly nodes & relationships")

run_cmd([sys.executable, "-u", "step6_export_neo4j.py", "--outdir", OUT])

print("\n✅ DONE. Các file dữ liệu cuối cùng trong graph_out/:")
print("  - edges_*.csv (edges gốc)")
print("  - node_details.(csv|json)")
print("  - nodes_*_props.csv")
print("  - neo4j_nodes_*.csv (node cho Neo4j)")
print("  - neo4j_rel_*.csv   (cạnh cho Neo4j)")
