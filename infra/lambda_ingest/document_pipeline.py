import pymupdf  # PyMuPDF
import os
from PIL import Image
import io
from llm_utils import describe_image_with_claude
import boto3
from urllib.parse import urlparse
from opensearch_insert import insert_passage_opensearch


def mark_document_chunks(markdown_text, n=3000, overlap=600):
    """
    Split a markdown document into chunks of approximately n characters with specified overlap,
    while preserving markdown structure and ensuring image tags are not split.

    Args:
        markdown_text (str): The markdown text to split
        n (int): Target chunk size in characters
        overlap (int): Number of characters to overlap between chunks

    Returns:
        list: A list of markdown chunks
    """
    # Check if input is empty
    if not markdown_text:
        return []

    chunks = []
    current_position = 0
    total_length = len(markdown_text)

    # Ensure the chunk size is reasonable
    if n <= overlap:
        n = overlap * 2

    while current_position < total_length:
        # Calculate the initial chunk boundaries
        chunk_end = min(current_position + n, total_length)

        # If we're not at the end, try to find a good breaking point
        if chunk_end < total_length:
            # First, make sure we don't break in the middle of an image markdown
            img_start = markdown_text.rfind("![", current_position, chunk_end)
            if img_start != -1:
                img_end = markdown_text.find(")", img_start)
                if img_end == -1 or img_end >= chunk_end:
                    # Image tag extends beyond our chunk - either extend the chunk or cut before the image
                    if (
                        img_end != -1 and img_end < current_position + n * 1.5
                    ):  # Don't extend chunk too much
                        chunk_end = img_end + 1
                    else:
                        chunk_end = img_start

            # If we're not at the end of a natural break, try to find one
            if chunk_end < total_length:
                # Look for paragraph breaks first
                paragraph_break = markdown_text.rfind(
                    "\n\n", current_position, chunk_end
                )
                if paragraph_break != -1 and paragraph_break > current_position + (
                    n // 4
                ):  # Ensure substantial chunk
                    chunk_end = paragraph_break + 2
                else:
                    # Try a line break
                    line_break = markdown_text.rfind("\n", current_position, chunk_end)
                    if line_break != -1 and line_break > current_position + (n // 4):
                        chunk_end = line_break + 1
                    else:
                        # Try a sentence break
                        sentence_end = max(
                            markdown_text.rfind(". ", current_position, chunk_end),
                            markdown_text.rfind("! ", current_position, chunk_end),
                            markdown_text.rfind("? ", current_position, chunk_end),
                        )
                        if sentence_end != -1 and sentence_end > current_position + (
                            n // 4
                        ):
                            chunk_end = sentence_end + 2
                        else:
                            # If we can't find a good break, just use a word boundary
                            space = markdown_text.rfind(
                                " ", current_position, chunk_end
                            )
                            if space != -1 and space > current_position + (n // 4):
                                chunk_end = space + 1

        # Add the chunk to our list
        current_chunk = markdown_text[current_position:chunk_end]
        chunks.append(current_chunk)

        # Move to the next position, ensuring we make progress
        next_position = chunk_end - overlap

        # Ensure we're making significant progress to avoid tiny chunks
        if next_position <= current_position:
            # If we can't move forward with overlap, move by at least n/2 characters
            next_position = current_position + max(n // 2, 1)

        current_position = min(
            next_position, total_length
        )  # Don't go beyond the end of the text

    return chunks


def save_image_to_s3(
    image, file_name, page_num, image_num, bucket_name, folder="image_store"
):
    """
    Saves a PIL image to an S3 bucket and returns the S3 URI.

    :param image: PIL Image to save.
    :param local_pdf_path: Path to the original PDF file.
    :param bucket_name: S3 bucket name.
    :param folder: Folder path in the S3 bucket.
    :return: S3 URI of the uploaded image.
    """
    s3_client = boto3.client("s3")

    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    buffered.seek(0)

    image_filename = f"{folder}/{file_name}_page_{page_num}_image_{image_num}.png"

    s3_client.upload_fileobj(
        buffered,
        bucket_name,
        image_filename,
        ExtraArgs={"ContentType": "image/png"},
    )

    # Construct and return the S3 URI
    s3_uri = f"s3://{bucket_name}/{image_filename}"
    return s3_uri


def process_image(page, block, model_id, image_count, pdf_path, bucket_name):
    """Takes in an image block, saves it to s3, and returns the description and uri in markdown format."""
    # Increase resolution with matrix parameter
    matrix = pymupdf.Matrix(4.0, 4.0)

    # Get image with higher resolution
    pix = page.get_pixmap(
        clip=pymupdf.Rect(block["bbox"]),
        matrix=matrix,
        alpha=False,  # Set to True if you need transparency
    )

    # Convert pixmap to PIL Image
    img_data = pix.samples
    pil_image = Image.frombytes("RGB", [pix.width, pix.height], img_data)

    # Optionally enhance the image quality
    pil_image = pil_image.convert("RGB")

    file_name = os.path.basename(pdf_path).replace(" ", "_")
    image_uri = save_image_to_s3(
        pil_image, file_name, page.number, image_count, bucket_name, os.getenv("IMAGE_FOLDER_NAME")
    )

    image_description = describe_image_with_claude(pil_image, model_id)

    return f"[{image_description}]({image_uri})"


def extract_lines_and_images(pdf_path, image_model_id, bucket_name):
    # Open the PDF document
    doc = pymupdf.open(pdf_path)

    image_count = 0  # Counter for naming image files

    document_lines = []
    for page_num, page in enumerate(doc):
        # Get the page dictionary
        page_dict = page.get_text("dict")
        # Extract blocks in order they appear on the page
        blocks = sorted(page_dict["blocks"], key=lambda b: (b["bbox"][1], b["bbox"][0]))
        for block in blocks:
            # Text block
            if "lines" in block:
                for line in block["lines"]:
                    line_text = " ".join([span["text"] for span in line["spans"]])
                    document_lines.append(line_text)
            # Image block
            elif "image" in block:
                image_count += 1

                image_markdown = process_image(
                    page, block, image_model_id, image_count, pdf_path, bucket_name
                )
                document_lines.append(image_markdown)

    page_count = doc.page_count

    doc.close()

    return "\n".join(document_lines), page_count


def download_from_s3_uri(s3_uri, local_directory="/tmp"):
    """
    Download a file from S3 using an S3 URI and save it locally.

    Args:
        s3_uri (str): The S3 URI in the format 's3://bucket-name/path/to/file'
        local_directory (str): Local directory to save the file (default: './downloads')

    Returns:
        str: Path to the downloaded file
    """
    try:
        # Parse the S3 URI
        parsed_uri = urlparse(s3_uri)
        bucket_name = parsed_uri.netloc
        s3_key = parsed_uri.path.lstrip("/")  # Remove leading slash

        # Get the filename from the S3 key
        file_name = os.path.basename(s3_key)

        # Create local directory if it doesn't exist
        os.makedirs(local_directory, exist_ok=True)

        # Construct local file path
        local_file_path = os.path.join(local_directory, file_name)

        # Initialize S3 client
        s3_client = boto3.client("s3")

        # Download the file
        print(f"Downloading {file_name} from S3...")
        s3_client.download_file(bucket_name, s3_key, local_file_path)
        print(f"Successfully downloaded to {local_file_path}")

        return local_file_path

    except Exception as e:
        print(f"Error downloading file from S3: {str(e)}")
        raise


def lambda_handler(event, context):
    try:
        s3_uri = event["uri"]
        bucket_name = event["bucket_name"]
        image_model_id = event["image_model_id"]
        embedding_model_id = event["embedding_model_id"]
        opensearch_index = event["opensearch_index"]
    except KeyError as e:
        return {"statusCode": 400, "body": f"Missing required field: {str(e)}"}

    local_pdf_path = download_from_s3_uri(s3_uri)

    markdown_text, num_pages = extract_lines_and_images(
        local_pdf_path, image_model_id, bucket_name
    )

    if num_pages > 2:
        document_chunks = mark_document_chunks(
            markdown_text, int(os.getenv("CHUNK_SIZE")), int(os.getenv("OVERLAP"))
        )
        for chunk in document_chunks:
            insert_passage_opensearch(
                chunk,
                s3_uri,
                embedding_model_id,
                os.getenv("OPENSEARCH_ENDPOINT"),
                opensearch_index,
            )
    else:
        insert_passage_opensearch(
            markdown_text,
            s3_uri,
            embedding_model_id,
            os.getenv("OPENSEARCH_ENDPOINT"),
            opensearch_index,
        )

    os.remove(local_pdf_path)

    print("Document {s3_uri} proccessed successfully!")

    return {"statusCode": 200, "body": f"Document {s3_uri} proccessed successfully!"}
