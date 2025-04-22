from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
import boto3
import yaml

# Script to delete all of the documents in a given opensearch index

config = yaml.safe_load(open("../config.yaml"))

region = config["region"]
service = "aoss"
host = config["opensearch_endpoint"]

session = boto3.Session()
credentials = session.get_credentials()
auth = AWSV4SignerAuth(credentials, region, service)

client = OpenSearch(
    hosts=[{"host": host, "port": 443}],
    http_auth=auth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection,
)
index_name = config["opensearch_index_name"]

# Fetch document IDs
search_body = {"_source": False, "size": 100, "query": {"match_all": {}}}
response = client.search(index=index_name, body=search_body)
document_ids = [hit["_id"] for hit in response["hits"]["hits"]]

# Delete each document by ID
for doc_id in document_ids:
    try:
        delete_response = client.delete(index=index_name, id=doc_id)
        print(f"Deleted document ID: {doc_id} | Result: {delete_response['result']}")
    except Exception as e:
        print(f"Error deleting document ID: {doc_id} | Error: {str(e)}")
