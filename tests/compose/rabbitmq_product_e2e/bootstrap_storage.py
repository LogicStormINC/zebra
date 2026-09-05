"""Create/version only the fixture bucket without credential-bearing CLI argv."""

import os

from botocore.config import Config
from botocore.session import Session


def main() -> None:
    if (os.environ["ZEBRA_S3_ENDPOINT"], os.environ["ZEBRA_S3_BUCKET"]) != (
        "http://minio:9000",
        "rabbitmq-product-e2e",
    ):
        raise ValueError("refusing non-fixture object store")
    client = Session().create_client(
        "s3",
        endpoint_url="http://minio:9000",
        region_name="us-east-1",
        aws_access_key_id=os.environ["ZEBRA_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["ZEBRA_S3_SECRET_KEY"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    bucket = "rabbitmq-product-e2e"
    try:
        client.create_bucket(Bucket=bucket)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass
    client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    print("isolated artifact bucket versioning enabled")


if __name__ == "__main__":
    main()
