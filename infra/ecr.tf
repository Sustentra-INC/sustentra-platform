# ECR repositories: <project>-<environment>-api and <project>-<environment>-web

resource "aws_ecr_repository" "app" {
  for_each = toset(var.ecr_repositories)

  name                 = "${local.name_prefix}-${each.key}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  for_each = aws_ecr_repository.app

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the last ${var.ecr_keep_last_images} images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.ecr_keep_last_images
        }
        action = { type = "expire" }
      },
    ]
  })
}

# Only the deploy role may push. Pulls (e.g. by the EC2 host in MVP-2) are
# still governed by normal IAM permissions.
data "aws_iam_policy_document" "ecr_push_only_deploy" {
  statement {
    sid    = "DenyPushExceptDeployRole"
    effect = "Deny"
    actions = [
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEquals"
      variable = "aws:PrincipalArn"
      values   = [aws_iam_role.deploy.arn]
    }
  }

  statement {
    sid    = "AllowPushFromDeployRole"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.deploy.arn]
    }
  }
}

resource "aws_ecr_repository_policy" "app" {
  for_each = aws_ecr_repository.app

  repository = each.value.name
  policy     = data.aws_iam_policy_document.ecr_push_only_deploy.json
}
