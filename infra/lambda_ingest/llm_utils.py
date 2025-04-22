from typing import Optional
import boto3
import json
import time
from botocore.exceptions import ClientError
import io
import base64
from botocore.config import Config

llm_config = Config(read_timeout=1200)


def describe_image_with_claude(image, model_id, max_tokens=1000):
    """
    Invokes Claude with a multimodal prompt to describe a PIL Image.
    Implements a simple exponential backoff for handling transient errors.

    Args:
        image (PIL.Image): The image to be described.
        max_tokens (int, optional): The maximum number of tokens to generate. Default is 500.

    Returns:
        dict: The response from Claude, or an error message if the call fails.
    """
    bedrock_session = boto3.session.Session()
    client = bedrock_session.client("bedrock-runtime")

    # Convert image to base64
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

    message = {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_base64,
                },
            },
            {
                "type": "text",
                "text": "Describe the given image.",
            },
        ],
    }

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": [message],
        }
    )

    for attempt in range(5):  # Retry up to 5 times
        try:
            response = client.invoke_model(body=body, modelId=model_id)
            response_body = json.loads(response.get("body").read())
            return response_body["content"][0]["text"]
        except ClientError as err:
            if err.response["Error"].get("Code") in [
                "ThrottlingException",
                "ServiceUnavailableException",
            ]:
                time.sleep(
                    2**attempt
                )  # Simple exponential backoff (1, 2, 4, 8, 16 sec)
            else:
                return {"error": err.response["Error"].get("Message", "Unknown error")}

    return {"error": "Request failed after retries"}
