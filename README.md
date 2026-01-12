# Elastic AI Workshop Assets

Assets for the "Build Smarter AI Apps" Instruqt workshop.

## Contents

### `/data`
- `police-incidents.json` - 1000 police incident records for bulk loading
- `load-incidents.sh` - Script to bulk load incidents into Elasticsearch

### `/app`
Full-stack search application:
- `backend/` - FastAPI application with Elasticsearch integration
- `frontend/` - React application with Elastic EUI components
- `docker-compose.yml` - Container orchestration

## Usage

These files are downloaded by the Instruqt track setup scripts.

```bash
# Clone to VM
git clone https://github.com/blakebholden/elastic-ai-workshop.git /opt/workshop-assets

# Copy data files
cp /opt/workshop-assets/data/* /root/data/

# Copy app files
cp -r /opt/workshop-assets/app/* /opt/kubernetes-vm/
```
