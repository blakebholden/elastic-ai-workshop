#!/usr/bin/env python3
"""
Bulk load police incidents into Elasticsearch with progress tracking.

This script loads incidents in batches with real-time progress updates,
showing elapsed time, documents per second, and estimated time remaining.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system("pip install requests -q")
    import requests

# Configuration
BATCH_SIZE = 100  # Documents per batch
DATA_FILE = Path("/root/data/police-incidents.json")
LOG_FILE = Path("/root/data/bulk-load.log")

def load_env():
    """Load environment variables from /root/.env"""
    env_file = Path("/root/.env")
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key, value)

    return {
        'es_url': os.environ.get('ES_URL', 'http://localhost:9200'),
        'es_api_key': os.environ.get('ES_API_KEY', ''),
        'es_index': os.environ.get('ES_INDEX', 'police-incidents'),
    }

def format_time(seconds):
    """Format seconds as human-readable time."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds//60:.0f}m {seconds%60:.0f}s"
    else:
        return f"{seconds//3600:.0f}h {(seconds%3600)//60:.0f}m"

def print_progress(current, total, start_time, errors=0):
    """Print a progress bar with statistics."""
    elapsed = time.time() - start_time
    docs_per_sec = current / elapsed if elapsed > 0 else 0
    remaining = (total - current) / docs_per_sec if docs_per_sec > 0 else 0

    pct = (current / total) * 100
    bar_width = 30
    filled = int(bar_width * current / total)
    bar = '=' * filled + '-' * (bar_width - filled)

    status = f"\r[{bar}] {pct:5.1f}% | {current:,}/{total:,} docs | {docs_per_sec:.1f}/sec | {format_time(elapsed)} elapsed"
    if current < total:
        status += f" | ~{format_time(remaining)} remaining"
    if errors > 0:
        status += f" | {errors} errors"

    print(status, end='', flush=True)

def test_connection(config):
    """Test Elasticsearch connection."""
    headers = {'Content-Type': 'application/json'}
    if config['es_api_key']:
        headers['Authorization'] = f"ApiKey {config['es_api_key']}"

    try:
        resp = requests.get(config['es_url'], headers=headers, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Connection failed: {e}")
        return False

def send_batch(config, batch_data, batch_num, log_file):
    """Send a batch to Elasticsearch."""
    headers = {
        'Content-Type': 'application/x-ndjson',
    }
    if config['es_api_key']:
        headers['Authorization'] = f"ApiKey {config['es_api_key']}"

    url = f"{config['es_url']}/{config['es_index']}/_bulk"

    try:
        resp = requests.post(url, data=batch_data, headers=headers, timeout=120)
        resp.raise_for_status()

        result = resp.json()

        # Log batch results
        log_file.write(f"\n=== Batch {batch_num} ===\n")
        log_file.write(f"Status: {resp.status_code}\n")

        if result.get('errors'):
            # Count and log errors
            errors = [item for item in result['items'] if item.get('index', {}).get('error')]
            log_file.write(f"Errors: {len(errors)}\n")
            for err in errors[:5]:  # Log first 5 errors
                log_file.write(f"  - {err['index']['error']['reason']}\n")
            return len(result['items']) - len(errors), len(errors)

        return len(result['items']), 0

    except requests.exceptions.Timeout:
        log_file.write(f"\n=== Batch {batch_num} TIMEOUT ===\n")
        return 0, BATCH_SIZE
    except Exception as e:
        log_file.write(f"\n=== Batch {batch_num} ERROR: {e} ===\n")
        return 0, BATCH_SIZE

def main():
    print("=" * 50)
    print("Police Incidents Bulk Loader (Python)")
    print("=" * 50)

    # Load configuration
    config = load_env()
    print(f"Elasticsearch: {config['es_url']}")
    print(f"Index: {config['es_index']}")
    print(f"Batch size: {BATCH_SIZE}")
    print(f"API Key: {'SET' if config['es_api_key'] else 'NOT SET'}")
    print()

    # Check data file
    if not DATA_FILE.exists():
        print(f"ERROR: Data file not found: {DATA_FILE}")
        sys.exit(1)

    # Test connection
    print("Testing connection...", end=' ')
    if not test_connection(config):
        sys.exit(1)
    print("OK")
    print()

    # Load documents
    print(f"Loading data from {DATA_FILE}...")
    with open(DATA_FILE) as f:
        documents = json.load(f)

    total_docs = len(documents)
    print(f"Found {total_docs:,} documents to load")
    print()

    # Process in batches
    print("Starting bulk load...")
    print("-" * 50)

    start_time = time.time()
    total_success = 0
    total_errors = 0
    batch_num = 0

    with open(LOG_FILE, 'w') as log_file:
        log_file.write(f"Bulk Load Started: {datetime.now()}\n")
        log_file.write(f"Total documents: {total_docs}\n")
        log_file.write(f"Batch size: {BATCH_SIZE}\n\n")

        for i in range(0, total_docs, BATCH_SIZE):
            batch_num += 1
            batch_docs = documents[i:i + BATCH_SIZE]

            # Build bulk request body
            bulk_lines = []
            for doc in batch_docs:
                # Add narrative_semantic field (copy of narrative for ELSER)
                doc_with_semantic = doc.copy()
                doc_with_semantic['narrative_semantic'] = doc['narrative']

                # Action line
                bulk_lines.append(json.dumps({"index": {"_id": doc['incident_id']}}))
                # Document line
                bulk_lines.append(json.dumps(doc_with_semantic))

            bulk_data = '\n'.join(bulk_lines) + '\n'

            # Send batch
            success, errors = send_batch(config, bulk_data, batch_num, log_file)
            total_success += success
            total_errors += errors

            # Update progress
            current = min(i + BATCH_SIZE, total_docs)
            print_progress(current, total_docs, start_time, total_errors)

            # Small delay between batches to let ELSER process
            if i + BATCH_SIZE < total_docs:
                time.sleep(1)

    # Final summary
    elapsed = time.time() - start_time
    print()
    print()
    print("-" * 50)
    print("LOAD COMPLETE")
    print("-" * 50)
    print(f"Time elapsed: {format_time(elapsed)}")
    print(f"Documents indexed: {total_success:,}")
    print(f"Errors: {total_errors:,}")
    print(f"Average speed: {total_success/elapsed:.1f} docs/sec")
    print()

    # Verify count
    print("Verifying index count...")
    time.sleep(3)

    headers = {'Content-Type': 'application/json'}
    if config['es_api_key']:
        headers['Authorization'] = f"ApiKey {config['es_api_key']}"

    try:
        resp = requests.get(
            f"{config['es_url']}/{config['es_index']}/_count",
            headers=headers,
            timeout=10
        )
        count = resp.json().get('count', 0)
        print(f"Documents in index: {count:,}")

        if count >= total_docs:
            print()
            print("SUCCESS! All documents loaded.")
        else:
            print()
            print(f"WARNING: Expected {total_docs:,}, found {count:,}")
            print(f"Check {LOG_FILE} for details")
    except Exception as e:
        print(f"Could not verify count: {e}")

    if total_errors > 0:
        print()
        print(f"See {LOG_FILE} for error details")

if __name__ == "__main__":
    main()
