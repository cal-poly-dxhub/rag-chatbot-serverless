import boto3
from langchain_aws import BedrockEmbeddings
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
import os


def generate_embedding(passage, model_id):
    """Generates an embedding vector given text"""
    embeddings_client = BedrockEmbeddings(model_id=model_id)

    embedding = embeddings_client.embed_query(passage)
    return embedding


def insert_into_opensearch(document, opensearch_endpoint, opensearch_index):
    """Inserts a dictionary of information (document) into opensearch"""
    service = "aoss"

    session = boto3.Session()
    credentials = session.get_credentials()
    auth = AWSV4SignerAuth(credentials, os.getenv("AWS_REGION"), service)

    client = OpenSearch(
        hosts=[{"host": opensearch_endpoint, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )

    response = client.index(index=opensearch_index, body=document)


def insert_passage_opensearch(
    passage, source_uri, model_id, opensearch_endpoint, opensearch_index
):
    """Takes in a text passage and inserts it into OpenSearch"""
    try:
        embedding = generate_embedding(passage, model_id)

        # Preparing document for OpenSearch
        document = {
            "passage": passage,
            "source_url": source_uri,
            "embedding": embedding,
        }

        insert_into_opensearch(document, opensearch_endpoint, opensearch_index)
    except Exception as e:
        print(f"Inserting {source_uri} into opensearch failed due to {e}")
