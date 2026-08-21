import logging
from typing import BinaryIO
from app.core.config import settings

logger = logging.getLogger("nexacare.utils.s3")


def upload_file_to_s3(file_obj: BinaryIO, object_name: str, content_type: str = None) -> str:
    """
    Uploads a file object to AWS S3 and returns the public URL.
    Falls back to local file storage if S3 credentials are not set.
    """
    bucket = (settings.AWS_STORAGE_BUCKET_NAME or "").strip()
    access_key = (settings.AWS_ACCESS_KEY_ID or "").strip()
    secret_key = (settings.AWS_SECRET_ACCESS_KEY or "").strip()
    region = (settings.AWS_REGION or "us-east-1").strip()

    if not bucket or not access_key or not secret_key:
        logger.info("AWS S3 credentials not fully configured. Using local disk fallback.")
        return ""

    try:
        import boto3
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
        
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        
        s3_client.upload_fileobj(file_obj, bucket, object_name, ExtraArgs=extra_args)
        
        # Build the public S3 URL
        url = f"https://{bucket}.s3.{region}.amazonaws.com/{object_name}"
        logger.info(f"File successfully uploaded to S3: {url}")
        return url
    except Exception as e:
        logger.error(f"Failed to upload file to S3: {e}")
        # Return empty string to trigger local fallback
        return ""
