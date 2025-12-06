# -*- coding: utf-8 -*-
"""
step7_clean_neo4j.py
- Làm sạch & chuẩn hoá các CSV Neo4j trước khi import.

1) neo4j_nodes_person.csv
   - Chuẩn hoá name & wiki_url theo tiêu đề thật trên vi.wikipedia.org
     (theo redirect / heading).
   - KHÔNG xoá node person nào, chỉ cập nhật thông tin.

2) neo4j_nodes_university.csv
   - Chuẩn hoá name & wiki_url theo tiêu đề thật trên vi.wikipedia.org.
   - Loại bỏ:
       * Các node mang tính khái niệm (ví dụ: “Đại học”).
       * Các URL không có bài viết tiếng Việt thật (trang báo
         “Wikipedia hiện chưa có bài viết nào với tên này”).
   - Sau khi xoá university, cập nhật lại các file cạnh:
       * neo4j_rel_alumni_of.csv
       * neo4j_rel_person_mentions_university.csv
       * neo4j_rel_university_mentions_person.csv
       * neo4j_rel_university_mentions_university.csv

Chạy:
    python step7_clean_neo4j.py
"""

import os
from pathlib import Path
import pandas as pd
import requests
from urllib.parse import unquote
from bs4 import BeautifulSoup

# tqdm (optional)
try:
    from tqdm import tqdm
    HAS_TQDM = True
except Exception:
    HAS_TQDM = False

OUT_DIR = Path("graph_out")

NODES_PERSON_FILE = "neo4j_nodes_person.csv"
NODES_UNI_FILE    = "neo4j_nodes_university.csv"

REL_FILES = {
    "alumni_of":                "neo4j_rel_alumni_of.csv",
    "person_mentions_uni":      "neo4j_rel_person_mentions_university.csv",
    "uni_mentions_person":      "neo4j_rel_university_mentions_person.csv",
    "uni_mentions_uni":         "neo4j_rel_university_mentions_university.csv",
    "shared_university":        "neo4j_rel_shared_university.csv",  # không cần đụng tới
}

VI_MISSING_MARKERS = [
    "Wikipedia hiện chưa có bài viết nào với tên này",
    "Wikipedia hiện chưa có bài viết nào với tên này."
]

UA = "UET-AlumniGraph/1.0"
HTTP_TIMEOUT = 10


# =======================
#   HÀM HỖ TRỢ CHUNG
# =======================

def fetch_wiki_meta(url: str):
    """
    Lấy meta từ một URL vi.wikipedia.org:
      - valid: False nếu trang là 'chưa có bài viết' hoặc HTTP lỗi.
      - heading: nội dung h1#firstHeading
      - final_url: URL sau redirect
      - canonical_title: segment cuối của final_url (decoded, space)
    """
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": UA},
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
        )
    except Exception:
        # lỗi mạng: coi như giữ nguyên
        return {
            "valid": True,
            "heading": None,
            "final_url": url,
            "canonical_title": None,
        }

    if resp.status_code != 200:
        return {
            "valid": False,
            "heading": None,
            "final_url": resp.url,
            "canonical_title": None,
        }

    text = resp.text
    if any(m in text for m in VI_MISSING_MARKERS):
        return {
            "valid": False,
            "heading": None,
            "final_url": resp.url,
            "canonical_title": None,
        }

    heading = None
    try:
        soup = BeautifulSoup(text, "html.parser")
        h1 = soup.find("h1", id="firstHeading")
        if h1:
            heading = h1.get_text(strip=True)
    except Exception:
        heading = None

    final_url = resp.url
    canonical_title = None
    try:
        if "/wiki/" in final_url:
            seg = final_url.split("/wiki/", 1)[1]
            seg = unquote(seg)
            seg = seg.split("#", 1)[0]
            canonical_title = seg.replace("_", " ").strip()
    except Exception:
        canonical_title = None

    return {
        "valid": True,
        "heading": heading,
        "final_url": final_url,
        "canonical_title": canonical_title,
    }


def is_generic_university_name(name: str) -> bool:
    """Heuristic loại các node 'khái niệm' như 'Đại học'."""
    if not isinstance(name, str):
        return False
    n = name.strip()
    return n == "Đại học"


# =======================
#   PERSON NODES
# =======================

def clean_person_nodes():
    path = OUT_DIR / NODES_PERSON_FILE
    if not path.exists():
        print(f"[Step7] Không tìm thấy file person: {path}")
        return

    dfp = pd.read_csv(path)
    if dfp.empty:
        print("[Step7] neo4j_nodes_person.csv trống, bỏ qua.")
        return

    print("[Step7] Chuẩn hoá Person nodes từ wiki_url …")

    it = dfp.iterrows()
    if HAS_TQDM:
        it = tqdm(it, total=len(dfp), desc="Normalizing persons", unit="node")

    changed = 0
    for idx, row in it:
        url = str(row["wiki_url"])
        meta = fetch_wiki_meta(url)

        if not meta["valid"]:
            # Person thật gần như luôn có bài viwiki, nếu không cứ giữ nguyên
            continue

        new_name = meta["heading"] or meta["canonical_title"] or row["name"]
        new_url = meta["final_url"] or url

        old_name = str(row["name"])
        if isinstance(new_name, str) and new_name.strip() and new_name.strip() != old_name.strip():
            dfp.at[idx, "name"] = new_name.strip()
            changed += 1
        dfp.at[idx, "wiki_url"] = new_url

    dfp.to_csv(path, index=False)
    print(f"[Step7] Person nodes: cập nhật name/wiki_url cho {changed} node.")


# =======================
#   UNIVERSITY NODES
# =======================

def clean_university_nodes():
    uni_path = OUT_DIR / NODES_UNI_FILE
    if not uni_path.exists():
        print(f"[Step7] Không tìm thấy file university: {uni_path}")
        return set()

    dfu = pd.read_csv(uni_path)
    if dfu.empty:
        print("[Step7] neo4j_nodes_university.csv trống, bỏ qua.")
        return set()

    print(f"[Step7] Số university ban đầu: {len(dfu)}")

    # 1) bỏ các tên khái niệm
    mask_generic = dfu["name"].apply(is_generic_university_name)
    generic_ids = set(dfu.loc[mask_generic, "id"].tolist())
    if generic_ids:
        print(f"[Step7] Loại {len(generic_ids)} university khái niệm (ví dụ 'Đại học').")
        dfu = dfu[~mask_generic].copy()
    removed_ids = set(generic_ids)

    # 2) chuẩn hoá theo wiki
    it = dfu.iterrows()
    if HAS_TQDM:
        it = tqdm(it, total=len(dfu), desc="Normalizing universities", unit="node")

    missing_ids = set()
    for idx, row in it:
        url = str(row["wiki_url"])
        meta = fetch_wiki_meta(url)

        if not meta["valid"]:
            missing_ids.add(int(row["id"]))
            continue

        new_name = meta["heading"] or meta["canonical_title"] or row["name"]
        new_url = meta["final_url"] or url

        if isinstance(new_name, str) and new_name.strip():
            dfu.at[idx, "name"] = new_name.strip()
        dfu.at[idx, "wiki_url"] = new_url

    if missing_ids:
        print(f"[Step7] Loại {len(missing_ids)} university không có bài viwiki thực sự.")
        dfu = dfu[~dfu["id"].isin(missing_ids)].copy()
        removed_ids |= missing_ids

    dfu = dfu.reset_index(drop=True)
    dfu.to_csv(uni_path, index=False)
    print(f"[Step7] Sau khi làm sạch còn {len(dfu)} university.")

    return removed_ids


# =======================
#   UPDATE RELATIONSHIPS
# =======================

def update_relationships(removed_unis: set):
    if not removed_unis:
        print("[Step7] Không có university nào bị xoá → không cần cập nhật cạnh.")
        return

    print(f"[Step7] Cập nhật các cạnh liên quan {len(removed_unis)} university bị xoá…")

    # ALUMNI_OF: dst_university_id
    path = OUT_DIR / REL_FILES["alumni_of"]
    if path.exists():
        df = pd.read_csv(path)
        before = len(df)
        df = df[~df["dst_university_id"].isin(removed_unis)].copy()
        df.to_csv(path, index=False)
        print(f"  - {REL_FILES['alumni_of']}: {before} → {len(df)} cạnh.")

    # PERSON_MENTIONS_UNIVERSITY: dst_university_id
    path = OUT_DIR / REL_FILES["person_mentions_uni"]
    if path.exists():
        df = pd.read_csv(path)
        before = len(df)
        df = df[~df["dst_university_id"].isin(removed_unis)].copy()
        df.to_csv(path, index=False)
        print(f"  - {REL_FILES['person_mentions_uni']}: {before} → {len(df)} cạnh.")

    # UNIVERSITY_MENTIONS_PERSON: src_university_id
    path = OUT_DIR / REL_FILES["uni_mentions_person"]
    if path.exists():
        df = pd.read_csv(path)
        before = len(df)
        df = df[~df["src_university_id"].isin(removed_unis)].copy()
        df.to_csv(path, index=False)
        print(f"  - {REL_FILES['uni_mentions_person']}: {before} → {len(df)} cạnh.")

    # UNIVERSITY_MENTIONS_UNIVERSITY: src/dst_university_id
    path = OUT_DIR / REL_FILES["uni_mentions_uni"]
    if path.exists():
        df = pd.read_csv(path)
        before = len(df)
        mask_keep = (~df["src_university_id"].isin(removed_unis)
                     & ~df["dst_university_id"].isin(removed_unis))
        df = df[mask_keep].copy()
        df.to_csv(path, index=False)
        print(f"  - {REL_FILES['uni_mentions_uni']}: {before} → {len(df)} cạnh.")


# =======================
#   MAIN
# =======================

def main():
    if not OUT_DIR.exists():
        print(f"[Step7] Thư mục output không tồn tại: {OUT_DIR}")
        return

    print("\n=== STEP 7 — Clean & normalize Neo4j CSVs ===")

    # 1) Person
    clean_person_nodes()

    # 2) University + update quan hệ
    removed_unis = clean_university_nodes()
    update_relationships(removed_unis)

    print("\n✅ STEP 7 DONE. Các file trong graph_out/ đã được chuẩn hoá, sẵn sàng import Neo4j.")


if __name__ == "__main__":
    main()
