"""
RAG Pipeline Stub
=================

This is a placeholder module for Challenge 6 when RAG hasn't been implemented yet.
The functions return None, which signals to main.py that RAG is not available.

You'll implement the real RAG pipeline in Challenge 8!
"""


async def retrieve_document(es_client, index: str, document_id: str):
    """Stub - returns None. Implement in Challenge 8."""
    return None


def build_prompt(document: dict) -> str:
    """Stub - returns empty string. Implement in Challenge 8."""
    return ""


async def generate_summary(es_client, inference_id: str, prompt: str):
    """Stub - returns None. Implement in Challenge 8."""
    return None
