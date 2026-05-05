"""
blob_storage.py
---------------
Upload a local video file to Azure Blob Storage (input container)
and download the final Markdown doc from the output container.
"""

import os
import pathlib
from azure.storage.blob import BlobServiceClient


def _client() -> BlobServiceClient:
    conn_str = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    return BlobServiceClient.from_connection_string(conn_str)


def upload_video(local_path: str) -> str:
    """Upload video to the input container and return the blob name."""
    container = os.environ.get("AZURE_STORAGE_INPUT_CONTAINER", "video-input")
    blob_name = pathlib.Path(local_path).name

    client = _client()
    container_client = client.get_container_client(container)

    # Create container if it does not exist yet
    try:
        container_client.create_container()
    except Exception:
        pass  # already exists

    with open(local_path, "rb") as f:
        container_client.upload_blob(name=blob_name, data=f, overwrite=True)

    print(f"[blob] Uploaded '{blob_name}' → container '{container}'")
    return blob_name


def upload_markdown(local_path: str, blob_name: str) -> str:
    """Upload the generated Markdown file to the output container."""
    container = os.environ.get("AZURE_STORAGE_OUTPUT_CONTAINER", "doc-output")

    client = _client()
    container_client = client.get_container_client(container)

    try:
        container_client.create_container()
    except Exception:
        pass

    with open(local_path, "rb") as f:
        container_client.upload_blob(name=blob_name, data=f, overwrite=True)

    print(f"[blob] Uploaded doc '{blob_name}' → container '{container}'")
    return blob_name


def get_video_url(blob_name: str) -> str:
    """Return the HTTPS URL for a blob in the input container (no SAS – for demo)."""
    conn_str = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    # Parse account name from connection string
    parts = dict(p.split("=", 1) for p in conn_str.split(";") if "=" in p)
    account = parts.get("AccountName", "unknown")
    container = os.environ.get("AZURE_STORAGE_INPUT_CONTAINER", "video-input")
    return f"https://{account}.blob.core.windows.net/{container}/{blob_name}"
