"""
Script to check if an opensearch index exists.
Creates index if it does not already exist.
"""

from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
import boto3
import yaml

config = yaml.safe_load(open("../config.yaml"))
service = "aoss"
# replace with your OpenSearch Service domain/Serverless endpoint
domain_endpoint = config["opensearch_endpoint"]

region = config["region"]

credentials = boto3.Session().get_credentials()
awsauth = AWSV4SignerAuth(credentials, region, service)
os_ = OpenSearch(
    hosts=[{"host": domain_endpoint, "port": 443}],
    http_auth=awsauth,
    use_ssl=True,
    verify_certs=True,
    timeout=300,
    # http_compress = True, # enables gzip compression for request bodies
    connection_class=RequestsHttpConnection,
)

mapping = {
    "mappings": {
        "properties": {
            "passsage": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword"}},
            },
            "embedding": {
                "type": "knn_vector",
                "dimension": 1024,
                "method": {
                    "engine": "nmslib",
                    "space_type": "cosinesimil",
                    "name": "hnsw",
                    "parameters": {},
                },
            },
            "source_url": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword"}},
            },
        }
    }
}


def check_create_index(domain_index):

    if not os_.indices.exists(index=domain_index):
        os_.indices.create(index=domain_index, body=mapping)
        # Verify that the index has been created
        if os_.indices.exists(index=domain_index):
            print(f"Index {domain_index} created successfully.")
        else:
            print(f"Failed to create index '{domain_index}'.")
    else:
        print(f"Index {domain_index} already exists!")
