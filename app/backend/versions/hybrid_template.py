"""
Hybrid Search Implementation
============================

Complete the three TODO sections below to build RRF hybrid search.

This module implements the hybrid search pattern:
1. Keyword (BM25) search for exact term matching
2. Semantic (ELSER) search for meaning understanding
3. RRF fusion to combine both approaches

Once complete, save this file and test with:
    curl -X POST http://localhost:8000/search/hybrid \
        -H "Content-Type: application/json" \
        -d '{"query": "armed robbery", "size": 3}'
"""


def build_keyword_query(query_text: str) -> dict:
    """
    STEP 1: Build the keyword (BM25) query

    Create a multi_match query that searches across multiple fields.

    TODO: Replace the empty dict with your query.

    Hint: Use multi_match with fields: narrative^2, incident_type, tags
    The ^2 boosts the narrative field to be twice as important.

    Expected structure:
    {
        "multi_match": {
            "query": query_text,
            "fields": [...]
        }
    }
    """
    # ============================================================
    # YOUR CODE HERE - Replace {} with your multi_match query
    # ============================================================
    keyword_query = {}

    return keyword_query


def build_semantic_query(query_text: str) -> dict:
    """
    STEP 2: Build the semantic query

    Create a semantic query that uses ELSER embeddings.

    TODO: Replace the empty dict with your query.

    Hint: Use the narrative_semantic field which has ELSER embeddings.

    Expected structure:
    {
        "semantic": {
            "field": "narrative_semantic",
            "query": query_text
        }
    }
    """
    # ============================================================
    # YOUR CODE HERE - Replace {} with your semantic query
    # ============================================================
    semantic_query = {}

    return semantic_query


def build_rrf_query(keyword_query: dict, semantic_query: dict, size: int, from_: int) -> dict:
    """
    STEP 3: Combine with RRF (Reciprocal Rank Fusion)

    Create an RRF retriever that combines keyword and semantic search.

    TODO: Replace the empty dict with your RRF query.

    Hint:
    - Use the "retriever" key with "rrf" inside
    - The "retrievers" array should contain both queries wrapped in "standard"
    - Set rank_window_size to 50 and rank_constant to 20
    - Include size, from, and _source excludes for narrative_semantic

    Expected structure:
    {
        "retriever": {
            "rrf": {
                "retrievers": [
                    {"standard": {"query": keyword_query}},
                    {"standard": {"query": semantic_query}}
                ],
                "rank_window_size": 50,
                "rank_constant": 20
            }
        },
        "size": size,
        "from": from_,
        "_source": {"excludes": ["narrative_semantic"]}
    }
    """
    # ============================================================
    # YOUR CODE HERE - Replace {} with your RRF retriever query
    # ============================================================
    rrf_query = {}

    return rrf_query
