#!/bin/bash
#
# Bulk load police incidents into Elasticsearch
# This script converts the JSON array to bulk format and loads in batches
#

set -e

# Source environment variables (ES_URL, ES_API_KEY)
if [ -f /root/.env ]; then
    source /root/.env
fi

ES_URL="${ES_URL:-http://localhost:9200}"
ES_API_KEY="${ES_API_KEY:-}"
ES_INDEX="${ES_INDEX:-police-incidents}"
DATA_FILE="${1:-/root/data/police-incidents.json}"
BATCH_SIZE=50
LOG_FILE="/root/data/bulk-load.log"

echo "=========================================="
echo "Police Incidents Bulk Loader"
echo "=========================================="
echo "Elasticsearch: $ES_URL"
echo "Index: $ES_INDEX"
echo "Data file: $DATA_FILE"
echo "Batch size: $BATCH_SIZE"
echo ""

# Check if data file exists
if [ ! -f "$DATA_FILE" ]; then
    echo "ERROR: Data file not found: $DATA_FILE"
    exit 1
fi

# Count total documents
TOTAL_DOCS=$(jq 'length' "$DATA_FILE")
echo "Total documents to load: $TOTAL_DOCS"
echo ""

# Clear log file
> "$LOG_FILE"

# Function to load a batch
load_batch() {
    local batch_file=$1
    local response

    if [ -n "$ES_API_KEY" ]; then
        response=$(curl -s -X POST "$ES_URL/$ES_INDEX/_bulk" \
            -H "Content-Type: application/x-ndjson" \
            -H "Authorization: ApiKey $ES_API_KEY" \
            --data-binary @"$batch_file")
    else
        response=$(curl -s -X POST "$ES_URL/$ES_INDEX/_bulk" \
            -H "Content-Type: application/x-ndjson" \
            --data-binary @"$batch_file")
    fi

    # Check for errors
    errors=$(echo "$response" | jq -r '.errors')
    if [ "$errors" = "true" ]; then
        echo "$response" | jq '.items[] | select(.index.error != null)' >> "$LOG_FILE"
        return 1
    fi
    return 0
}

# Create temp file for batch
BATCH_FILE=$(mktemp)
trap "rm -f $BATCH_FILE" EXIT

# Process documents in batches
doc_count=0
batch_count=0
error_count=0

echo "Loading documents..."
echo ""

# Process each document
jq -c '.[]' "$DATA_FILE" | while read -r doc; do
    # Get the incident_id for the document ID
    id=$(echo "$doc" | jq -r '.incident_id')

    # Add narrative_semantic field (copy of narrative for semantic search)
    narrative=$(echo "$doc" | jq -r '.narrative')
    doc=$(echo "$doc" | jq --arg ns "$narrative" '. + {narrative_semantic: $ns}')

    # Write action and document to batch file
    echo "{\"index\":{\"_id\":\"$id\"}}" >> "$BATCH_FILE"
    echo "$doc" >> "$BATCH_FILE"

    doc_count=$((doc_count + 1))

    # When batch is full, send it
    if [ $((doc_count % BATCH_SIZE)) -eq 0 ]; then
        batch_count=$((batch_count + 1))

        if load_batch "$BATCH_FILE"; then
            printf "\rLoaded: %d / %d documents (batch %d)" "$doc_count" "$TOTAL_DOCS" "$batch_count"
        else
            error_count=$((error_count + 1))
            printf "\rLoaded: %d / %d documents (batch %d - ERRORS)" "$doc_count" "$TOTAL_DOCS" "$batch_count"
        fi

        # Clear batch file
        > "$BATCH_FILE"

        # Small delay to avoid overwhelming ELSER
        sleep 2
    fi
done

# Load any remaining documents
if [ -s "$BATCH_FILE" ]; then
    batch_count=$((batch_count + 1))
    if load_batch "$BATCH_FILE"; then
        printf "\rLoaded: %d / %d documents (batch %d)" "$TOTAL_DOCS" "$TOTAL_DOCS" "$batch_count"
    else
        error_count=$((error_count + 1))
    fi
fi

echo ""
echo ""
echo "=========================================="
echo "Load Complete!"
echo "=========================================="
echo "Documents loaded: $TOTAL_DOCS"
echo "Batches processed: $batch_count"

if [ $error_count -gt 0 ]; then
    echo "Batches with errors: $error_count"
    echo "See $LOG_FILE for details"
fi

# Verify final count
echo ""
echo "Verifying index count..."
sleep 2
if [ -n "$ES_API_KEY" ]; then
    INDEXED_COUNT=$(curl -s "$ES_URL/$ES_INDEX/_count" \
        -H "Authorization: ApiKey $ES_API_KEY" | jq '.count')
else
    INDEXED_COUNT=$(curl -s "$ES_URL/$ES_INDEX/_count" | jq '.count')
fi
echo "Documents in index: $INDEXED_COUNT"

if [ "$INDEXED_COUNT" -ge "$TOTAL_DOCS" ]; then
    echo ""
    echo "SUCCESS! All documents loaded."
else
    echo ""
    echo "WARNING: Some documents may not have been indexed."
    echo "Expected: $TOTAL_DOCS, Found: $INDEXED_COUNT"
fi
