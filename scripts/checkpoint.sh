#!/bin/bash
# =============================================================================
# CHECKPOINT VERIFICATION SCRIPT
# =============================================================================
# This script verifies and fixes workshop state at various checkpoints.
# Call with a checkpoint level to ensure all prerequisites are met.
#
# Usage: ./checkpoint.sh <level>
#   level 1: Serverless provisioned + credentials available
#   level 2: ELSER deployed and started
#   level 3: Index created + data loaded (1000 docs)
#   level 5: App deployed and running
#   level 6: Modular Python files in place (hybrid_template)
#   level 8: Hybrid complete + RAG template in place
#   level 10: All modules complete
#
# Example: ./checkpoint.sh 5  # Ensures everything up to Challenge 5 is ready
# =============================================================================

set -e

CHECKPOINT_LEVEL=${1:-1}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[✓]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }
log_fixing() { echo -e "${YELLOW}[→]${NC} Fixing: $1"; }

# =============================================================================
# CHECKPOINT 1: Serverless + Credentials
# =============================================================================
checkpoint_1() {
    echo "=== Checkpoint 1: Serverless + Credentials ==="

    # Check for credentials
    if [ ! -f /root/.env ]; then
        log_warn "Credentials not found"

        # Try to extract from project_results.json
        JSON_FILE="/tmp/project_results.json"
        if [ -f "$JSON_FILE" ]; then
            log_fixing "Extracting credentials from project_results.json"
            REGION=$(jq -r 'keys[0]' "$JSON_FILE")
            ES_URL=$(jq -r ".\"$REGION\".endpoints.elasticsearch" "$JSON_FILE")
            ES_API_KEY=$(jq -r ".\"$REGION\".credentials.api_key" "$JSON_FILE")
            KIBANA_URL=$(jq -r ".\"$REGION\".endpoints.kibana" "$JSON_FILE")

            cat > /root/.env << EOF
ES_URL=$ES_URL
ES_API_KEY=$ES_API_KEY
KIBANA_URL=$KIBANA_URL
ES_INDEX=police-incidents
EOF
            log_info "Created /root/.env"
        else
            log_error "No credentials available - serverless may not be provisioned"
            log_fixing "Attempting to provision serverless..."
            /opt/workshops/start_serverless.sh --project-type elasticsearch --optimized-for vector
            sleep 5
            # Retry credential extraction
            if [ -f "$JSON_FILE" ]; then
                REGION=$(jq -r 'keys[0]' "$JSON_FILE")
                ES_URL=$(jq -r ".\"$REGION\".endpoints.elasticsearch" "$JSON_FILE")
                ES_API_KEY=$(jq -r ".\"$REGION\".credentials.api_key" "$JSON_FILE")
                KIBANA_URL=$(jq -r ".\"$REGION\".endpoints.kibana" "$JSON_FILE")
                cat > /root/.env << EOF
ES_URL=$ES_URL
ES_API_KEY=$ES_API_KEY
KIBANA_URL=$KIBANA_URL
ES_INDEX=police-incidents
EOF
                log_info "Serverless provisioned and credentials saved"
            else
                log_error "Failed to provision serverless"
                return 1
            fi
        fi
    else
        log_info "Credentials found"
    fi

    source /root/.env

    # Verify ES connection
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$ES_URL" -H "Authorization: ApiKey $ES_API_KEY" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" != "200" ]; then
        log_error "Cannot connect to Elasticsearch (HTTP $HTTP_CODE)"
        return 1
    fi
    log_info "Elasticsearch connection verified"
}

# =============================================================================
# CHECKPOINT 2: ELSER Deployed (verification only - users deploy in Challenge 4)
# =============================================================================
checkpoint_2() {
    echo "=== Checkpoint 2: ELSER Deployed ==="
    source /root/.env

    # Check if ELSER is deployed using the inference API
    ELSER_CHECK=$(curl -s -X GET "$ES_URL/_inference/sparse_embedding/.elser-2-elasticsearch" \
        -H "Authorization: ApiKey $ES_API_KEY" \
        -H "Content-Type: application/json" 2>/dev/null | jq -r '.inference_id // empty')

    if [ -z "$ELSER_CHECK" ]; then
        log_warn "ELSER not deployed - users will deploy in Challenge 4"
        # Don't auto-deploy - users do this manually in Challenge 4
    else
        log_info "ELSER is deployed"
    fi
}

# =============================================================================
# CHECKPOINT 3: Index + Data
# =============================================================================
checkpoint_3() {
    echo "=== Checkpoint 3: Index + Data ==="
    source /root/.env

    # Check if index exists
    INDEX_CHECK=$(curl -s -o /dev/null -w "%{http_code}" "$ES_URL/police-incidents" \
        -H "Authorization: ApiKey $ES_API_KEY" 2>/dev/null)

    if [ "$INDEX_CHECK" == "404" ]; then
        log_warn "Index does not exist"
        log_fixing "Creating index with mapping..."

        curl -s -X PUT "$ES_URL/police-incidents" \
            -H "Authorization: ApiKey $ES_API_KEY" \
            -H "Content-Type: application/json" \
            -d '{
          "mappings": {
            "properties": {
              "incident_id": {"type": "keyword"},
              "incident_datetime": {"type": "date"},
              "report_datetime": {"type": "date"},
              "incident_type": {"type": "keyword"},
              "incident_subtype": {"type": "keyword"},
              "severity": {"type": "keyword"},
              "narrative": {"type": "text"},
              "narrative_semantic": {"type": "semantic_text", "inference_id": ".elser-2-elasticsearch"},
              "address_block": {"type": "text"},
              "location": {"type": "geo_point"},
              "district": {"type": "keyword"},
              "neighborhood": {"type": "keyword"},
              "resolution": {"type": "keyword"},
              "arrest_made": {"type": "boolean"},
              "responding_units": {"type": "integer"},
              "injuries_reported": {"type": "boolean"},
              "weapon_involved": {"type": "keyword"},
              "property_damage": {"type": "boolean"},
              "estimated_loss": {"type": "float"},
              "victim_count": {"type": "integer"},
              "tags": {"type": "keyword"}
            }
          }
        }' > /dev/null
        log_info "Index created"
    else
        log_info "Index exists"
    fi

    # Check document count
    DOC_COUNT=$(curl -s "$ES_URL/police-incidents/_count" \
        -H "Authorization: ApiKey $ES_API_KEY" 2>/dev/null | jq '.count // 0')

    if [ "$DOC_COUNT" -lt 900 ]; then
        log_warn "Insufficient data ($DOC_COUNT docs, need ~1000)"
        log_fixing "Loading incident data..."

        # Check for data loading script
        if [ -f /root/data/load-incidents.sh ]; then
            cd /root/data && ./load-incidents.sh
        elif [ -f /opt/workshop-assets/data/load-incidents.sh ]; then
            cd /opt/workshop-assets/data && ./load-incidents.sh
        else
            log_error "Data loading script not found"
            return 1
        fi

        # Verify data loaded
        sleep 5
        DOC_COUNT=$(curl -s "$ES_URL/police-incidents/_count" \
            -H "Authorization: ApiKey $ES_API_KEY" 2>/dev/null | jq '.count // 0')
        log_info "Data loaded ($DOC_COUNT docs)"
    else
        log_info "Data present ($DOC_COUNT docs)"
    fi
}

# =============================================================================
# CHECKPOINT 5: App Deployed
# =============================================================================
checkpoint_5() {
    echo "=== Checkpoint 5: App Deployed ==="
    source /root/.env

    # Clone/update workshop assets if needed
    REPO_URL="https://github.com/blakebholden/elastic-ai-workshop.git"
    ASSETS_DIR="/opt/workshop-assets"

    if [ ! -d "$ASSETS_DIR" ]; then
        log_warn "Workshop assets not found"
        log_fixing "Cloning workshop assets..."
        git clone "$REPO_URL" "$ASSETS_DIR"
        log_info "Workshop assets cloned"
    else
        log_info "Workshop assets present"
    fi

    # Ensure app directory exists
    if [ ! -d "/opt/kubernetes-vm" ]; then
        log_warn "App directory not found"
        log_fixing "Setting up app directory..."
        mkdir -p /opt/kubernetes-vm
        cp -r "$ASSETS_DIR/app/"* /opt/kubernetes-vm/
        log_info "App directory created"
    else
        log_info "App directory exists"
    fi

    # Ensure app .env exists
    if [ ! -f "/opt/kubernetes-vm/.env" ]; then
        log_warn "App .env not found"
        log_fixing "Creating app .env..."
        cat > /opt/kubernetes-vm/.env << EOF
ES_URL=$ES_URL
ES_API_KEY=$ES_API_KEY
ES_INDEX=police-incidents
HYBRID_ENABLED=false
LLM_ENABLED=false
RAG_ENABLED=false
CHAT_ENABLED=false
LLM_INFERENCE_ID=redhat-granite
DEBUG=false
EOF
        log_info "App .env created"
    else
        log_info "App .env exists"
    fi

    # Check if Docker is running
    if ! systemctl is-active --quiet docker 2>/dev/null; then
        log_warn "Docker not running"
        log_fixing "Starting Docker..."
        systemctl start docker
        sleep 3
        log_info "Docker started"
    else
        log_info "Docker running"
    fi

    # Check if app containers are running
    cd /opt/kubernetes-vm
    RUNNING=$(docker-compose ps --services --filter "status=running" 2>/dev/null | wc -l)

    if [ "$RUNNING" -lt 2 ]; then
        log_warn "App containers not running ($RUNNING services)"
        log_fixing "Starting app containers..."
        docker-compose up -d
        sleep 10
        log_info "App containers started"
    else
        log_info "App containers running"
    fi

    # Verify backend is responding
    BACKEND_CHECK=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/health" 2>/dev/null || echo "000")
    if [ "$BACKEND_CHECK" != "200" ]; then
        log_warn "Backend not responding (HTTP $BACKEND_CHECK)"
        log_fixing "Restarting app containers..."
        docker-compose down 2>/dev/null || true
        docker-compose up -d
        sleep 15
    fi
    log_info "Backend responding"
}

# =============================================================================
# CHECKPOINT 6: Modular Files (Hybrid Template)
# =============================================================================
checkpoint_6() {
    echo "=== Checkpoint 6: Modular Files (Hybrid Template) ==="

    ASSETS_DIR="/opt/workshop-assets"
    APP_DIR="/opt/kubernetes-vm/backend"

    # Copy modular main.py
    if [ ! -f "$APP_DIR/main.py" ] || ! grep -q "from hybrid import" "$APP_DIR/main.py" 2>/dev/null; then
        log_warn "Modular main.py not in place"
        log_fixing "Installing modular main.py..."
        cp "$ASSETS_DIR/app/backend/versions/main_modular.py" "$APP_DIR/main.py"
        log_info "Modular main.py installed"
    else
        log_info "Modular main.py in place"
    fi

    # Copy hybrid template
    if [ ! -f "$APP_DIR/hybrid.py" ]; then
        log_warn "hybrid.py not found"
        log_fixing "Installing hybrid_template.py..."
        cp "$ASSETS_DIR/app/backend/versions/hybrid_template.py" "$APP_DIR/hybrid.py"
        log_info "hybrid.py installed"
    else
        log_info "hybrid.py exists"
    fi

    # Copy rag stub
    if [ ! -f "$APP_DIR/rag.py" ]; then
        log_warn "rag.py not found"
        log_fixing "Installing rag_stub.py..."
        cp "$ASSETS_DIR/app/backend/versions/rag_stub.py" "$APP_DIR/rag.py"
        log_info "rag.py installed"
    else
        log_info "rag.py exists"
    fi
}

# =============================================================================
# CHECKPOINT 8: Hybrid Complete + RAG Template
# =============================================================================
checkpoint_8() {
    echo "=== Checkpoint 8: Hybrid Complete + RAG Template ==="

    ASSETS_DIR="/opt/workshop-assets"
    APP_DIR="/opt/kubernetes-vm/backend"

    # Ensure hybrid.py is complete (not template)
    if grep -q "YOUR CODE HERE" "$APP_DIR/hybrid.py" 2>/dev/null; then
        log_warn "hybrid.py still has TODOs"
        log_fixing "Installing completed hybrid.py..."
        cp "$ASSETS_DIR/app/backend/versions/hybrid_complete.py" "$APP_DIR/hybrid.py"
        log_info "hybrid.py completed"
    else
        log_info "hybrid.py is complete"
    fi

    # Copy rag template (reset to template for Challenge 8)
    log_fixing "Installing rag_template.py for Challenge 8..."
    cp "$ASSETS_DIR/app/backend/versions/rag_template.py" "$APP_DIR/rag.py"
    log_info "rag.py template installed"
}

# =============================================================================
# CHECKPOINT 10: All Modules Complete
# =============================================================================
checkpoint_10() {
    echo "=== Checkpoint 10: All Modules Complete ==="

    ASSETS_DIR="/opt/workshop-assets"
    APP_DIR="/opt/kubernetes-vm/backend"

    # Ensure hybrid.py is complete
    if grep -q "YOUR CODE HERE" "$APP_DIR/hybrid.py" 2>/dev/null; then
        log_fixing "Installing completed hybrid.py..."
        cp "$ASSETS_DIR/app/backend/versions/hybrid_complete.py" "$APP_DIR/hybrid.py"
        log_info "hybrid.py completed"
    else
        log_info "hybrid.py is complete"
    fi

    # Ensure rag.py is complete
    if grep -q "YOUR CODE HERE" "$APP_DIR/rag.py" 2>/dev/null; then
        log_fixing "Installing completed rag.py..."
        cp "$ASSETS_DIR/app/backend/versions/rag_complete.py" "$APP_DIR/rag.py"
        log_info "rag.py completed"
    else
        log_info "rag.py is complete"
    fi
}

# =============================================================================
# MAIN: Run checkpoints up to specified level
# =============================================================================
echo "========================================"
echo "CHECKPOINT VERIFICATION (Level $CHECKPOINT_LEVEL)"
echo "========================================"
echo ""

# Run checkpoints sequentially up to the specified level
if [ "$CHECKPOINT_LEVEL" -ge 1 ]; then checkpoint_1; echo ""; fi
if [ "$CHECKPOINT_LEVEL" -ge 2 ]; then checkpoint_2; echo ""; fi
if [ "$CHECKPOINT_LEVEL" -ge 3 ]; then checkpoint_3; echo ""; fi
if [ "$CHECKPOINT_LEVEL" -ge 5 ]; then checkpoint_5; echo ""; fi
if [ "$CHECKPOINT_LEVEL" -ge 6 ]; then checkpoint_6; echo ""; fi
if [ "$CHECKPOINT_LEVEL" -ge 8 ]; then checkpoint_8; echo ""; fi
if [ "$CHECKPOINT_LEVEL" -ge 10 ]; then checkpoint_10; echo ""; fi

echo "========================================"
echo "CHECKPOINT $CHECKPOINT_LEVEL COMPLETE"
echo "========================================"
