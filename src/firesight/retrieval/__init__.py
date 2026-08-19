"""The two retrievers and the router that chooses between them.

    sql_agent.py    -- natural language -> validated read-only SQL -> result (M1)
    vector_store.py -- embedding search + optional cross-encoder rerank (M2)
    router.py       -- structured / unstructured / hybrid / out_of_scope (M3)
"""
