"""
RAG Pipeline Implementation (Complete)
======================================

This module implements the RAG pattern:
1. RETRIEVE - Get the document from Elasticsearch
2. AUGMENT - Build a prompt with the document context
3. GENERATE - Call the LLM to produce a summary
"""


async def retrieve_document(es_client, index: str, document_id: str):
    """
    STEP 1: RETRIEVE - Get the document from Elasticsearch

    Fetch the incident document by its ID.
    """
    doc_resp = await es_client.get(
        index=index,
        id=document_id,
        source_excludes=["narrative_semantic"],
    )

    return doc_resp


def build_prompt(document: dict) -> str:
    """
    STEP 2: AUGMENT - Build the prompt with document context

    Create a prompt that includes the document details for the LLM.
    """
    prompt = f"""Summarize this police incident in 2-3 bullet points. Focus on: what happened, where, and the outcome.

Incident Type: {document.get('incident_type', 'Unknown')}
Location: {document.get('address_block', 'Unknown')}, {document.get('district', '')} District
Resolution: {document.get('resolution', 'Unknown')}

Narrative:
{document.get('narrative', 'No narrative available.')}

Provide a brief summary:"""

    return prompt


async def generate_summary(es_client, inference_id: str, prompt: str):
    """
    STEP 3: GENERATE - Call the LLM via Elasticsearch Inference API

    Send the prompt to the LLM and get a summary back.
    """
    inference_resp = await es_client.inference.inference(
        model_id=inference_id,
        task_type="completion",
        input=prompt,
    )

    return inference_resp
