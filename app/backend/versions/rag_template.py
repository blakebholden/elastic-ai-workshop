"""
RAG Pipeline Implementation
===========================

Complete the three TODO sections below to implement the RAG pattern:
1. RETRIEVE - Get the document from Elasticsearch
2. AUGMENT - Build a prompt with the document context
3. GENERATE - Call the LLM to produce a summary

Once complete, save this file and test with:
    curl -X POST http://localhost:8000/rag/summarize \
        -H "Content-Type: application/json" \
        -d '{"document_id": "YOUR_DOC_ID"}'
"""


async def retrieve_document(es_client, index: str, document_id: str):
    """
    STEP 1: RETRIEVE - Get the document from Elasticsearch

    Fetch the incident document by its ID.

    TODO: Replace 'None' with your code to retrieve the document.

    Hint: Use es_client.get() with:
    - index: the index name
    - id: the document_id
    - source_excludes: ["narrative_semantic"] (to exclude the large embedding field)

    Expected code:
        doc_resp = await es_client.get(
            index=index,
            id=document_id,
            source_excludes=["narrative_semantic"],
        )
    """
    # ============================================================
    # YOUR CODE HERE - Replace None with your es_client.get() call
    # ============================================================
    doc_resp = None

    return doc_resp


def build_prompt(document: dict) -> str:
    """
    STEP 2: AUGMENT - Build the prompt with document context

    Create a prompt that includes the document details for the LLM.

    TODO: Replace the empty string with your prompt template.

    Hint: Use an f-string that includes:
    - Instructions for the LLM (summarize in 2-3 bullet points)
    - Key fields: incident_type, address_block, district, resolution
    - The full narrative text
    - A closing instruction

    Expected structure:
        prompt = f\"\"\"Summarize this police incident in 2-3 bullet points...

        Incident Type: {document.get('incident_type', 'Unknown')}
        ...
        Narrative:
        {document.get('narrative', 'No narrative available.')}

        Provide a brief summary:\"\"\"
    """
    # ============================================================
    # YOUR CODE HERE - Replace "" with your prompt f-string
    # ============================================================
    prompt = ""

    return prompt


async def generate_summary(es_client, inference_id: str, prompt: str):
    """
    STEP 3: GENERATE - Call the LLM via Elasticsearch Inference API

    Send the prompt to the LLM and get a summary back.

    TODO: Replace 'None' with your inference call.

    Hint: Use es_client.inference.inference() with:
    - model_id: the inference_id (e.g., "redhat-granite")
    - task_type: "completion"
    - input: the prompt string

    Expected code:
        inference_resp = await es_client.inference.inference(
            model_id=inference_id,
            task_type="completion",
            input=prompt,
        )
    """
    # ============================================================
    # YOUR CODE HERE - Replace None with your inference call
    # ============================================================
    inference_resp = None

    return inference_resp
