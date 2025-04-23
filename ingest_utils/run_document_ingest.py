"""
Script to run document ingest on lambdas.
For every document in your s3 bucket's ingest folder a
new lambda will be spawned to process it.
"""

import aioboto3
import asyncio
import json
from os_index_creator import check_create_index
import yaml
from botocore.config import Config
import boto3
from typing import List, Set
import os
from datetime import datetime


timeout_config = Config(
    read_timeout=900,  # 15 minutes
    connect_timeout=60,  # Optional, but useful
    retries={"max_attempts": 3},
)

config = yaml.safe_load(open("../config.yaml"))

os.environ["AWS_DEFAULT_REGION"] = config["region"]

function_name = config["ingest_lambda_name"]


def list_s3_pdfs(bucket_name: str, prefix: str) -> List[str]:
    """
    List all PDF file URIs in a given S3 bucket folder (prefix).

    Args:
        bucket_name (str): Name of the S3 bucket.
        prefix (str): Folder path within the bucket (with trailing slash).

    Returns:
        List[str]: List of S3 URIs ending in .pdf
    """
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

    uris = []
    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith(".pdf"):
                uris.append(f"s3://{bucket_name}/{key}")

    return uris


def get_previously_processed_uris(bucket_name: str) -> Set[str]:
    """
    Get the set of URIs that were previously successfully processed.
    Creates the cache file in S3 if it does not exist.

    Args:
        bucket_name (str): Name of the S3 bucket

    Returns:
        Set[str]: Set of URIs that were previously processed
    """
    s3 = boto3.client("s3")
    key = config["ingest_cache_file"]

    try:
        s3.head_object(Bucket=bucket_name, Key=key)

        # File exists, get its content
        response = s3.get_object(Bucket=bucket_name, Key=key)
        content = response["Body"].read().decode("utf-8")
        uris = set(line.strip() for line in content.splitlines() if line.strip())

        print(f"Found {len(uris)} previously processed URIs")
        return uris

    except s3.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            print("No previous successful URIs file found. Creating an empty one...")
            s3.put_object(Bucket=bucket_name, Key=key, Body="")  # create empty file
        else:
            print(f"Error checking successful URIs file: {str(e)}")
        return set()

    except Exception as e:
        print(f"Error reading successful URIs file: {str(e)}")
        return set()


def update_successful_uris(
    bucket_name: str,
    new_successful_uris: List[str],
    previously_processed: Set[str] = None,
) -> None:
    """
    Update the list of successfully processed URIs in S3.

    Args:
        bucket_name (str): Name of the S3 bucket
        new_successful_uris (List[str]): List of newly successful URI strings
        previously_processed (Set[str]): Previously processed URIs to include
    """
    # Combine new successful URIs with previously processed URIs
    all_successful = set(new_successful_uris)
    if previously_processed:
        all_successful.update(previously_processed)

    # Convert to sorted list for consistent output
    all_successful_list = sorted(all_successful)

    # Join URIs with newlines
    content = "\n".join(all_successful_list)

    # Upload to S3 (overwriting the existing file)
    s3_client = boto3.client("s3")
    s3_client.put_object(
        Bucket=bucket_name, Key=config["ingest_cache_file"], Body=content
    )

    cache_file = config["ingest_cache_file"]
    print(f"\nSuccessful URIs file updated: s3://{bucket_name}/{cache_file}")
    print(f"Total successful files: {len(all_successful_list)}")


async def invoke_lambda(session, uri):
    """
    Invoke Lambda function for a single URI.

    Args:
        session: aioboto3 session
        uri (str): URI to process

    Returns:
        dict: Result with URI and success status
    """
    # Extract filename from URI for cleaner display
    filename = os.path.basename(uri)
    print(f"⏳ Processing: {filename}")

    async with session.client("lambda", config=timeout_config) as lambda_client:
        try:
            response = await lambda_client.invoke(
                FunctionName=function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(
                    {
                        "uri": uri,
                        "bucket_name": config["input_bucket_name"],
                        "image_model_id": config["model"]["image"],
                        "embedding_model_id": config["model"]["embedding"],
                        "opensearch_index": config["opensearch_index_name"],
                    }
                ).encode(),
            )

            payload = await response["Payload"].read()
            result = json.loads(payload)

            status_code = result.get("statusCode")

            if status_code == 200:
                print(f"✅ {filename}")
                if "body" in result:
                    print(f"   {result['body']}")
                return {"uri": uri, "success": True}
            else:
                print(f"❌ {filename} (Status: {status_code})")
                if "body" in result:
                    print(f"   Error: {result['body']}")
                return {"uri": uri, "success": False}

        except Exception as e:
            print(f"❌ {filename} (Exception)")
            print(f"   Error: {str(e)}")
            return {"uri": uri, "success": False}


async def main():
    # Print header
    print("\n" + "=" * 80)
    print(f" PDF INGESTION PROCESS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # Get previously processed URIs
    previously_processed = get_previously_processed_uris(config["input_bucket_name"])

    # Get all PDF files from S3
    all_uris = list_s3_pdfs(config["input_bucket_name"], config["file_input_folder"])
    print(f"\nFound {len(all_uris)} total PDF files")

    # Filter out previously processed URIs
    uris_to_process = [uri for uri in all_uris if uri not in previously_processed]
    print(f"Found {len(uris_to_process)} new PDF files to process")

    # If no new files to process, exit early
    if not uris_to_process:
        print("\nNo new files to process. Exiting.")
        return

    # Check/create index
    check_create_index(config["opensearch_index_name"])
    print(f"OpenSearch index '{config['opensearch_index_name']}' ready\n")
    print("-" * 80)

    # Process files
    async with aioboto3.Session().client("lambda") as lambda_client:
        tasks = [invoke_lambda(aioboto3.Session(), uri) for uri in uris_to_process]
        results = await asyncio.gather(*tasks)

    # Filter for successful URIs only
    newly_successful_uris = [
        result["uri"] for result in results if result.get("success")
    ]

    # Update the successful URIs file in S3
    update_successful_uris(
        config["input_bucket_name"], newly_successful_uris, previously_processed
    )

    # Print summary
    success_count = len(newly_successful_uris)
    print("\n" + "-" * 80)
    print(
        f"SUMMARY: {success_count}/{len(uris_to_process)} new files processed successfully"
    )
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
