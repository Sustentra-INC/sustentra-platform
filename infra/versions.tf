terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Partial config: bucket/key/region come from environments/<env>.s3.tfbackend
  #   terraform init -backend-config=environments/prod.s3.tfbackend
  # State locking uses an S3 lock file (use_lockfile = true), no DynamoDB.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  # Fails fast if the active credentials belong to any other AWS account
  # (e.g. if AWS_PROFILE is not set to "sustentra").
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
