#!/bin/bash
#
# Bulk load police incidents into Elasticsearch
# This script converts the JSON array to bulk format and loads in batches
#

# Don't exit on error - we want to see what fails
set +e

# Source environment variables (ES_URL, ES_API_KEY)
if [ -f /root/.env ]; then
    echo "Sourcing /root/.env..."
    source /root/.env
else
    echo "WARNING: /root/.env not found"
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
echo "API Key: ${ES_API_KEY:+SET (${#ES_API_KEY} chars)}${ES_API_KEY:-NOT SET}"
echo ""

# Check if data file exists
if [ ! -f "$DATA_FILE" ]; then
    echo "ERROR: Data file not found: $DATA_FILE"
    exit 1
fi

# Test connection first
echo "Testing Elasticsearch connection..."
if [ -n "$ES_API_KEY" ]; then
    TEST_RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" "$ES_URL" \
        -H "Authorization: ApiKey $ES_API_KEY")
else
    TEST_RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" "$ES_URL")
fi

HTTP_CODE=$(echo "$TEST_RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)
BODY=$(echo "$TEST_RESPONSE" | grep -v "HTTP_CODE:")

echo "Connection test HTTP code: $HTTP_CODE"
if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: Failed to connect to Elasticsearch"
    echo "Response: $BODY"
    exit 1
fi
echo "Connection successful!"
echo ""

# Check if index exists
echo "Checking index '$ES_INDEX'..."
if [ -n "$ES_API_KEY" ]; then
    INDEX_RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" "$ES_URL/$ES_INDEX" \
        -H "Authorization: ApiKey $ES_API_KEY")
else
    INDEX_RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" "$ES_URL/$ES_INDEX")
fi

HTTP_CODE=$(echo "$INDEX_RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)
if [ "$HTTP_CODE" != "200" ]; then
    echo "WARNING: Index '$ES_INDEX' may not exist (HTTP $HTTP_CODE)"
    echo "You may need to create the index first in Challenge 2"
fi
echo ""

# Count total documents
TOTAL_DOCS=$(jq 'length' "$DATA_FILE")
echo "Total documents to load: $TOTAL_DOCS"
echo ""

# Clear log file
> "$LOG_FILE"

# Function to load a batch
load_batch() {
    local batch_file=$1
    local batch_num=$2
    local response

    if [ -n "$ES_API_KEY" ]; then
        response=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$ES_URL/$ES_INDEX/_bulk" \
            -H "Content-Type: application/x-ndjson" \
            -H "Authorization: ApiKey $ES_API_KEY" \
            --data-binary @"$batch_file")
    else
        response=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$ES_URL/$ES_INDEX/_bulk" \
            -H "Content-Type: application/x-ndjson" \
            --data-binary @"$batch_file")
    fi

    local http_code=$(echo "$response" | grep "HTTP_CODE:" | cut -d: -f2)
    local body=$(echo "$response" | grep -v "HTTP_CODE:")

    # Log everything for debugging
    echo "=== Batch $batch_num ===" >> "$LOG_FILE"
    echo "HTTP Code: $http_code" >> "$LOG_FILE"

    if [ "$http_code" != "200" ]; then
        echo "ERROR: Batch $batch_num failed with HTTP $http_code" | tee -a "$LOG_FILE"
        echo "Response: $body" >> "$LOG_FILE"
        echo "First 500 chars of response: ${body:0:500}"
        return 1
    fi

    # Check for bulk errors in response
    local errors=$(echo "$body" | jq -r '.errors // "parse_error"')
    if [ "$errors" = "true" ]; then
        echo "Batch $batch_num had document errors" >> "$LOG_FILE"
        echo "$body" | jq '.items[] | select(.index.error != null) | .index.error' >> "$LOG_FILE"

        # Show first error inline
        local first_error=$(echo "$body" | jq -r '.items[] | select(.index.error != null) | .index.error.reason' | head -1)
        echo ""
        echo "  First error: $first_error"
        return 1
    elif [ "$errors" = "parse_error" ]; then
        echo "Could not parse response" >> "$LOG_FILE"
        echo "Raw response: $body" >> "$LOG_FILE"
        return 1
    fi

    # Count successful items
    local success_count=$(echo "$body" | jq '[.items[] | select(.index.status == 200 or .index.status == 201)] | length')
    echo "Batch $batch_num: $success_count documents indexed successfully" >> "$LOG_FILE"

    return 0
}

# Create temp file for batch
BATCH_FILE=$(mktemp)
trap "rm -f $BATCH_FILE" EXIT

# Process documents in batches
doc_count=0
batch_count=0
error_count=0
success_count=0

echo "Loading documents..."
echo ""

# Process each document - use jq to add narrative_semantic and output both lines
jq -c '.[] | {action: {index: {_id: .incident_id}}, doc: (. + {narrative_semantic: .narrative})}' "$DATA_FILE" | while read -r item; do
    # Extract action and doc as separate lines
    echo "$item" | jq -c '.action' >> "$BATCH_FILE"
    echo "$item" | jq -c '.doc' >> "$BATCH_FILE"

    doc_count=$((doc_count + 1))

    # When batch is full, send it
    if [ $((doc_count % BATCH_SIZE)) -eq 0 ]; then
        batch_count=$((batch_count + 1))

        if load_batch "$BATCH_FILE" "$batch_count"; then
            success_count=$((success_count + BATCH_SIZE))
            printf "\rLoaded: %d / %d documents (batch %d)          " "$doc_count" "$TOTAL_DOCS" "$batch_count"
        else
            error_count=$((error_count + 1))
            printf "\rLoaded: %d / %d documents (batch %d - ERRORS)  " "$doc_count" "$TOTAL_DOCS" "$batch_count"
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
    if load_batch "$BATCH_FILE" "$batch_count"; then
        printf "\rLoaded: %d / %d documents (batch %d)          " "$TOTAL_DOCS" "$TOTAL_DOCS" "$batch_count"
    else
        error_count=$((error_count + 1))
    fi
fi

echo ""
echo ""
echo "=========================================="
echo "Load Complete!"
echo "=========================================="
echo "Documents processed: $TOTAL_DOCS"
echo "Batches processed: $batch_count"

if [ $error_count -gt 0 ]; then
    echo "Batches with errors: $error_count"
    echo ""
    echo "See $LOG_FILE for details"
    echo "Quick view: tail -100 $LOG_FILE"
fi

# Verify final count
echo ""
echo "Verifying index count..."
sleep 3
if [ -n "$ES_API_KEY" ]; then
    COUNT_RESPONSE=$(curl -s "$ES_URL/$ES_INDEX/_count" \
        -H "Authorization: ApiKey $ES_API_KEY")
else
    COUNT_RESPONSE=$(curl -s "$ES_URL/$ES_INDEX/_count")
fi

echo "Count response: $COUNT_RESPONSE"
INDEXED_COUNT=$(echo "$COUNT_RESPONSE" | jq '.count // 0')
echo "Documents in index: $INDEXED_COUNT"

if [ "$INDEXED_COUNT" -ge "$TOTAL_DOCS" ] 2>/dev/null; then
    echo ""
    echo "SUCCESS! All documents loaded."
else
    echo ""
    echo "WARNING: Document count mismatch."
    echo "Expected: $TOTAL_DOCS, Found: $INDEXED_COUNT"
    echo ""
    echo "Check the log file for errors: $LOG_FILE"
fi
