"""
Hybrid Search Implementation (Complete)
========================================

This module implements the hybrid search pattern:
1. Keyword (BM25) search for exact term matching
2. Semantic (ELSER) search for meaning understanding
3. RRF fusion to combine both approaches
"""


def build_keyword_query(query_text: str) -> dict:
    """
    STEP 1: Build the keyword (BM25) query

    Create a multi_match query that searches across multiple fields.
    """
    keyword_query = {
        "multi_match": {
            "query": query_text,
            "fields": ["narrative^2", "incident_type", "tags"]
        }
    }

    return keyword_query


def build_semantic_query(query_text: str) -> dict:
    """
    STEP 2: Build the semantic query

    Create a semantic query that uses ELSER embeddings.
    """
    semantic_query = {
        "semantic": {
            "field": "narrative_semantic",
            "query": query_text
        }
    }

    return semantic_query


def build_rrf_query(keyword_query: dict, semantic_query: dict, size: int, from_: int) -> dict:
    """
    STEP 3: Combine with RRF (Reciprocal Rank Fusion)

    Create an RRF retriever that combines keyword and semantic search.
    """
    rrf_query = {
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

    return rrf_query
