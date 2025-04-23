# Helpdesk Chatbot Solution


## Table of Contents
- [Collaboration](#collaboration)
- [Disclaimers](#disclaimers)
- [Overview](#chatbot-overview)
- [Deployment Steps](#deployment-steps)



# Collaboration
Thanks for your interest in our solution.  Having specific examples of replication and cloning allows us to continue to grow and scale our work. If you clone or download this repository, kindly shoot us a quick email to let us know you are interested in this work!

[wwps-cic@amazon.com] 

# Disclaimers

**Customers are responsible for making their own independent assessment of the information in this document.**

**This document:**

(a) is for informational purposes only, 

(b) represents current AWS product offerings and practices, which are subject to change without notice, and 

(c) does not create any commitments or assurances from AWS and its affiliates, suppliers or licensors. AWS products or services are provided “as is” without warranties, representations, or conditions of any kind, whether express or implied. The responsibilities and liabilities of AWS to its customers are controlled by AWS agreements, and this document is not part of, nor does it modify, any agreement between AWS and its customers. 

(d) is not to be considered a recommendation or viewpoint of AWS

**Additionally, all prototype code and associated assets should be considered:**

(a) as-is and without warranties

(b) not suitable for production environments

(d) to include shortcuts in order to support rapid prototyping such as, but not limitted to, relaxed authentication and authorization and a lack of strict adherence to security best practices

**All work produced is open source. More information can be found in the GitHub repo.**

## Author
- Nick Riley - njriley@calpoly.edu


## Chatbot Overview
- The [DxHub](https://dxhub.calpoly.edu/challenges/) developed a helpdesk chatbot solution that can answer user questions pulling from their knowledge base articles. The chatbot contains many features: 

    #### Intelligent Question Answering
    - Leverages Retrieval Augmented Generation (RAG) for accurate and contextual responses
    - Dynamic context integration for more relevant and precise answers
    - Real-time information retrieval

    #### Advanced Image Capabilities
    - Seamless processing of images within documents
    - Visual context integration in responses
    - Inline image display in user interface

    #### Source Attribution
    - Direct links to source documents
    - Easy access to reference materials

    #### Smart Document Processing
    - Intelligent parsing of PDF documents
    - Advanced text and image extraction

    #### Scalability and Versitility
    - Serverless architecture enables automatic scaling
    - API-first design supports multiple frontend implementations

## Deployment Steps

## Prerequisites
- AWS CDK CLI
- Docker
- Python 3.x
- AWS credentials
- Bedrock Model access for all used models
- Git

Clone the repo:
```bash
git clone https://github.com/cal-poly-dxhub/calbright-assistant.git
```

Install `requirements.txt`:
```bash
cd calbright-assistant
python3 -m venv .venv
source .venv/bin/activate
pip3 install -r requirements.txt
```

### 1. Infrastructure Deployment
```bash
cd cdk

# Activate virual env
source .venv/bin/activate

# Synthesize the CloudFormation template
cdk synth

# Deploy the stack
cdk deploy
```

### 2. Configuration Setup
After deployment, update the config file with CDK outputs:
| Parameter | Description |
|-----------|-------------|
| `ingest_lambda_name` | Lambda function name for ingestion |
| `opensearch_endpoint` | OpenSearch cluster endpoint |
| `rag_api_endpoint` | RAG API endpoint URL |
| `api_key` | API Key (obtain from console under API keys) |
| `region` | AWS Region |
| `chat_prompt` | Fill in your organization's name |

### 3. File Upload to S3
Upload local files to S3 bucket with the specified prefix:
```bash
aws s3 cp your-pdf-directory/ s3://your-document-bucket/files-to-process/ --recursive
```

### 4. Document Processing

#### Reset Document Cache (if needed)
- The system includes a file cache to prevent duplicate processing
- Run the below command to clear the cache if needed

```bash
cd ingest_utils
python3 reset_document_cache.py
```

#### Run Document Ingestion
- Ensure all configuration values are properly set before running the ingestion process (see step 2)
```bash
python3 run_document_ingest.py
```

### 5. Testing
Once document ingestion is complete, you can test the system using either:

Command line interface:
```bash
python3 chat_test.py
```

OR

Web interface:
```bash
streamlit run chat_frontend.py
```


## Troubleshooting
- Ensure docker is running and you have access to it. To grant access run:
```bash
sudo usermod -aG docker $USER # Give docker access to current user
newgrp docker # Refresh group
```
- Verify AWS credentials are properly configured
- Check S3 bucket permissions
- Ensure all required dependencies are installed
- Verify API endpoints are accessible via `chat_test.py`
- If hitting throttling errors, try changing the chat model

## Known Bugs/Concerns
- Quick PoC with no intent verification or error checking

## Support
For any queries or issues, please contact:
- Darren Kraker, Sr Solutions Architect - dkraker@amazon.com
- Nick Riley, Software Developer Intern - njriley@calpoly.edu