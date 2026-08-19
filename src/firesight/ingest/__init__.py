"""ETL into DuckDB (structured) and Chroma (unstructured).

    structured.py  -- NFIRS flat files + local export -> DuckDB tables (M1)
    documents.py   -- reference corpus -> chunks -> embeddings -> Chroma (M2)
"""
