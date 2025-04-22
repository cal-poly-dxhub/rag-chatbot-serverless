import json
import logging
from botocore.exceptions import ClientError
from search_utils import generate_text_embedding
from opensearch_query import get_documents, generate_short_uuid
import boto3
import os
import re
from urllib.parse import urlparse
from botocore.exceptions import NoCredentialsError

# set up logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")


def invoke_model(prompt, model_id, max_tokens=4096):
    """
    Calls Bedrock for a given modelid

    Args:
        prompt (str): The text prompt to send to the model
        model_id (str): The model identifier
        max_tokens (int): Maximum number of tokens to generate

    Returns:
        str: The text response from the model
    """
    bedrock = boto3.client("bedrock-runtime")

    try:
        inference_config = {"maxTokens": max_tokens, "temperature": 1, "topP": 0.999}
        messages = [{"role": "user", "content": [{"text": prompt}]}]

        response = bedrock.converse(
            modelId=model_id,
            messages=messages,
            inferenceConfig=inference_config,
        )

        return response["output"]["message"]["content"][0]["text"]

    except Exception as e:
        print(f"Error calling the model: {str(e)}")
        return None


def s3_uri_to_presigned_url(s3_uri, expiration=3600):
    """
    Convert an S3 URI to a presigned URL

    Args:
        s3_uri (str): S3 URI in format 's3://bucket-name/path/to/file'
        expiration (int): URL expiration time in seconds (default: 1 hour)

    Returns:
        str: Presigned URL or None if there's an error
    """
    try:
        # Parse the S3 URI
        parsed_uri = urlparse(s3_uri)
        bucket_name = parsed_uri.netloc
        object_key = parsed_uri.path.lstrip("/")

        # Create S3 client
        s3_client = boto3.client("s3")

        # Generate presigned URL
        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_key},
            ExpiresIn=expiration,
        )
        return presigned_url

    except NoCredentialsError:
        print("AWS credentials not found")
        return None
    except Exception as e:
        print(f"Error: {str(e)}")
        return None


def get_filename_from_s3_uri(s3_uri):
    """Extract just the filename from an S3 URI"""
    parsed_uri = urlparse(s3_uri)
    # Get the full path and extract the filename using os.path.basename
    return os.path.basename(parsed_uri.path)


def process_text(text, uuid_mapping):
    """Replaces s3 uris and uuids with presign urls to sources."""

    def replace_image_uri(match):
        s3_uri = match.group(0)[4:-1]
        if s3_uri:
            presigned_url = s3_uri_to_presigned_url(s3_uri)
            file_name = get_filename_from_s3_uri(s3_uri)
            return f"![{file_name}]({presigned_url})"
        return "![]()"

    # First replace all S3 URIs in image markdown
    image_pattern = r"!\[\]\(s3://[^\)]+\)"
    text = re.sub(image_pattern, replace_image_uri, text)

    # Then replace all UUIDs with their corresponding sources
    uuid_pattern = r"<([a-f0-9]{8})>"

    def replace_uuid(match):
        uuid = match.group(1)
        s3_uri = uuid_mapping.get(uuid)
        if s3_uri:
            presigned_url = s3_uri_to_presigned_url(s3_uri)
            file_name = get_filename_from_s3_uri(s3_uri)
            return f"[{file_name}]({presigned_url})"
        return "[]()"

    text = re.sub(uuid_pattern, replace_uuid, text)

    return text


def generate_source_mapping(documents):
    """Generates a mapping from a generated uuid:source url for llm to read."""
    source_mapping = {}
    for item in documents:
        if item.get("_source"):
            print(f"Passage: {item['_source']['passage']}\nScore: {item['_score']}\n")

            source_id = generate_short_uuid()
            source_mapping[source_id] = item["_source"]["source_url"]

    return source_mapping


def lambda_handler(event, context):
    try:
        body_data = json.loads(event["body"])
        user_query = body_data["query"]

        embedding = generate_text_embedding(user_query)

        selected_docs = get_documents(user_query, embedding)

        source_mapping = generate_source_mapping(selected_docs)

        prompt = (
            "User:"
            + user_query
            + os.getenv("CHAT_PROMPT").format(
                documents=selected_docs, citations=str(source_mapping)
            )
        )

        model_response = invoke_model(prompt, os.getenv("CHAT_MODEL_ID"))

        parsed_chat_respose = process_text(model_response, source_mapping)

        return {"statusCode": 200, "body": json.dumps(parsed_chat_respose)}

    except Exception as e:
        logger.error(f"Error in lambda_handler: {e}")
        return {"statusCode": 500, "body": json.dumps("Error processing message")}
