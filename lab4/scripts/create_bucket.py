#!/usr/bin/env python3
"""
creates the S3 bucket on Sufy.

Usage:
    pip install boto3
    python scripts/create_bucket.py
"""

import os
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT_URL"],
    aws_access_key_id=os.environ["S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    region_name=os.environ.get("S3_REGION", "auto"),
    config=Config(signature_version="s3v4"),
)

BUCKET = os.environ["S3_BUCKET"]

try:
    s3.create_bucket(Bucket=BUCKET)
    print(f"✓ Bucket '{BUCKET}' created.")
except ClientError as e:
    code = e.response["Error"]["Code"]
    if code in ("BucketAlreadyExists", "BucketAlreadyOwnedByYou"):
        print(f"Bucket '{BUCKET}' already exists — nothing to do.")
    else:
        raise
