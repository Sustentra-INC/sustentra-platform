# One-time bootstrap: creates ONLY the S3 bucket that holds Terraform state.
#
# This is applied once from a laptop with local state, then its own state is
# migrated into the bucket it created (see infra/README.md, step 2).

terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "project" {
  description = "Project name, used as the first part of every resource name."
  type        = string
  default     = "sustentra"
}

variable "aws_region" {
  description = "AWS region for the state bucket."
  type        = string
  default     = "us-east-1"
}

variable "aws_account_id" {
  description = "The only AWS account this config is allowed to touch."
  type        = string
  default     = "012751249540"
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Component = "bootstrap"
    }
  }
}

locals {
  state_bucket_name = "${var.project}-tfstate-${var.aws_account_id}"
}

resource "aws_s3_bucket" "tfstate" {
  bucket = local.state_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

data "aws_iam_policy_document" "tfstate_tls_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    resources = [
      aws_s3_bucket.tfstate.arn,
      "${aws_s3_bucket.tfstate.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  policy = data.aws_iam_policy_document.tfstate_tls_only.json

  depends_on = [aws_s3_bucket_public_access_block.tfstate]
}

output "state_bucket_name" {
  value = aws_s3_bucket.tfstate.bucket
}
