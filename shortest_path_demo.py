def build_graph(outdir="graph_out", use_weighted=False):
    """
    Đọc các file CSV trong graph_out và xây NetworkX graph.

    Node:
        - từ node_details.csv  -> type="person" / "university"

    Edge (undirected):
        - edges_alumni_pu.csv       : Person -- University (ALUMNI_OF)
        - edges_shared_uni_pp.csv   : Person -- Person (SHARED_UNI)
        - edges_mentions_pp.csv     : Person -- Person (MENTIONS_PERSON)
        - edges_mentions_pu.csv     : Person -- University (MENTIONS_UNIVERSITY)
        - edges_uni_mentions_p.csv  : University -- Person (UNI_MENTIONS_PERSON)
        - edges_uni_mentions_u.csv  : University -- University (UNIVERSITY_MENTIONS_UNIVERSITY)
    """
    G = nx.Graph()

    # -------- NODES --------
    node_details_fp = os.path.join(outdir, "node_details.csv")
    if not os.path.exists(node_details_fp):
        raise SystemExit(
            f"❌ Không tìm thấy node_details.csv trong {outdir}/.\n"
            f"   Hãy chạy run_pipeline_clean.py trước để sinh dữ liệu."
        )

    nodes_df = pd.read_csv(node_details_fp)

    for _, row in nodes_df.iterrows():
        title = str(row.get("title", "")).strip()
        ntype = str(row.get("type", "unknown")).strip().lower() or "unknown"
        if not title:
            continue
        if not G.has_node(title):
            G.add_node(title, type=ntype)

    # Helper: add/merge edge với weight
    def add_edge(u, v, relation, extra=None, weight=1.0):
        if not u or not v or u == v:
            return
        extra = extra or {}
        if G.has_edge(u, v):
            old_w = G[u][v].get("weight", weight)
            G[u][v]["weight"] = min(old_w, weight)
            # update relation / extra nếu muốn
        else:
            attrs = {"relation": relation, "weight": weight}
            attrs.update(extra)
            G.add_edge(u, v, **attrs)

    # -------- ALUMNI_OF --------
    edges_alumni_fp = os.path.join(outdir, "edges_alumni_pu.csv")
    if os.path.exists(edges_alumni_fp):
        alumni_df = pd.read_csv(edges_alumni_fp)
        for _, row in alumni_df.iterrows():
            p = str(row.get("src_person", "")).strip()
            u = str(row.get("dst_university", "")).strip()
            year = row.get("year", "")
            add_edge(p, u, "ALUMNI_OF", extra={"year": year}, weight=1.0)

    # -------- SHARED_UNI --------
    edges_shared_fp = os.path.join(outdir, "edges_shared_uni_pp.csv")
    if os.path.exists(edges_shared_fp):
        shared_df = pd.read_csv(edges_shared_fp)
        for _, row in shared_df.iterrows():
            a = str(row.get("src_person", "")).strip()
            b = str(row.get("dst_person", "")).strip()
            count = row.get("count", 1)
            try:
                c = float(count)
                if use_weighted and c > 0:
                    w = 1.0 / c  # học chung nhiều => gần hơn
                else:
                    w = 1.0
            except Exception:
                w = 1.0
            add_edge(a, b, "SHARED_UNI", extra={"count": count}, weight=w)

    # -------- MENTIONS_PERSON (P-P) --------
    edges_mp_fp = os.path.join(outdir, "edges_mentions_pp.csv")
    if os.path.exists(edges_mp_fp):
        mp_df = pd.read_csv(edges_mp_fp)
        for _, row in mp_df.iterrows():
            a = str(row.get("src_person", "")).strip()
            b = str(row.get("dst_person", "")).strip()
            add_edge(a, b, "MENTIONS_PERSON", weight=1.0)

    # -------- MENTIONS_UNIVERSITY (P-U) --------
    edges_mpu_fp = os.path.join(outdir, "edges_mentions_pu.csv")
    if os.path.exists(edges_mpu_fp):
        mpu_df = pd.read_csv(edges_mpu_fp)
        for _, row in mpu_df.iterrows():
            p = str(row.get("src_person", "")).strip()
            u = str(row.get("dst_university", "")).strip()
            add_edge(p, u, "MENTIONS_UNIVERSITY", weight=1.0)

    # -------- UNI_MENTIONS_PERSON (U-P) --------
    edges_ump_fp = os.path.join(outdir, "edges_uni_mentions_p.csv")
    if os.path.exists(edges_ump_fp):
        ump_df = pd.read_csv(edges_ump_fp)
        for _, row in ump_df.iterrows():
            u = str(row.get("src_university", "")).strip()
            p = str(row.get("dst_person", "")).strip()
            add_edge(u, p, "UNI_MENTIONS_PERSON", weight=1.0)

    # -------- UNIVERSITY_MENTIONS_UNIVERSITY (U-U) --------
    edges_uu_fp = os.path.join(outdir, "edges_uni_mentions_u.csv")
    if os.path.exists(edges_uu_fp):
        uu_df = pd.read_csv(edges_uu_fp)
        for _, row in uu_df.iterrows():
            u1 = str(row.get("src_university", "")).strip()
            u2 = str(row.get("dst_university", "")).strip()
            add_edge(u1, u2, "UNIVERSITY_MENTIONS_UNIVERSITY", weight=1.0)

    print(f"✅ Đã build graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    return G
