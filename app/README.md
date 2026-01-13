# Police Incident Search Application

A full-stack application demonstrating AI-powered search capabilities with Elasticsearch.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│           React Frontend (Elastic EUI)                       │
│                    Port 3000                                 │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              FastAPI Backend                                 │
│                  Port 8000                                   │
│  /search/keyword | /search/semantic | /search/hybrid        │
│  /search/filtered | /chat/document | /chat/summarize        │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Elasticsearch                                   │
│  - ELSER for semantic search                                │
│  - Hybrid search with RRF                                   │
│  - Inference API for LLM                                    │
└─────────────────────────────────────────────────────────────┘
```

## Features

- **4 Search Types**:
  - **Keyword**: Traditional BM25 text matching
  - **Semantic**: ELSER-powered understanding
  - **Hybrid**: RRF fusion of keyword + semantic
  - **Filtered**: Hybrid with metadata filters

- **Interactive Map**: Visualize incidents geographically
  - Color-coded by incident type
  - Filter by district and crime type
  - Click markers for incident details

- **RAG Chat**: Ask questions about specific incidents
- **AI Summaries**: Generate incident summaries

## Quick Start

### Prerequisites

1. Elasticsearch instance with:
   - `police-incidents` index created and populated
   - ELSER model deployed
   - (Optional) `redhat-granite` inference endpoint for chat

### Docker Deployment

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your Elasticsearch credentials

# 2. Build and run
docker-compose up --build

# 3. Access the app
open http://localhost:3000
```

### Local Development

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set environment variables
export ES_URL="your-es-url"
export ES_API_KEY="your-api-key"

python main.py
```

**Frontend:**
```bash
cd frontend
npm install
npm start
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/stats` | GET | Index statistics |
| `/search/keyword` | POST | BM25 keyword search |
| `/search/semantic` | POST | ELSER semantic search |
| `/search/hybrid` | POST | RRF hybrid search |
| `/search/filtered` | POST | Filtered hybrid search |
| `/document/{id}` | GET | Get single document |
| `/documents/similar/{id}` | GET | Find similar documents |
| `/documents/map` | GET | Get incidents for map view |
| `/chat/document` | POST | Chat about a document |
| `/chat/summarize` | POST | Generate summary |

## Search Request Example

```json
POST /search/hybrid
{
  "query": "armed robbery convenience store",
  "size": 10
}
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ES_URL` | Elasticsearch URL | `http://localhost:9200` |
| `ES_API_KEY` | API key for authentication | - |
| `ES_INDEX` | Index name | `police-incidents` |
| `LLM_INFERENCE_ID` | ES Inference endpoint ID | `redhat-granite` |
| `LLM_API_KEY` | Direct LLM API key (fallback) | - |
| `LLM_API_BASE` | Direct LLM base URL (fallback) | - |
| `LLM_MODEL` | LLM model name | `granite-3-3-8b-instruct` |

## Workshop Integration

This application is designed for the "Build Smarter AI Apps" Instruqt workshop. Participants:

1. Create the Elasticsearch index with semantic_text fields
2. Ingest police incident documents
3. Configure the LLM inference endpoint
4. Deploy and test this application
5. Experiment with different search types

## License

For workshop use only.
