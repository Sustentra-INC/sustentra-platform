# "deploy" role: used by the app deploy pipeline (MVP-5).
# Can push images to ECR, run commands on the app host via SSM,
# and take an RDS snapshot before migrations.

resource "aws_iam_role" "deploy" {
  name                 = "${local.name_prefix}-deploy"
  description          = "GitHub Actions deploy role (ECR push, SSM SendCommand, RDS snapshot)"
  assume_role_policy   = data.aws_iam_policy_document.github_actions_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPushPull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:ListImages",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [for repo in aws_ecr_repository.app : repo.arn]
  }

  # SendCommand needs permission on both the target instance and the document.
  statement {
    sid       = "SsmSendCommandToAppHosts"
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ec2:${var.aws_region}:${var.aws_account_id}:instance/*"]

    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/Project"
      values   = [var.project]
    }

    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/Environment"
      values   = [var.environment]
    }
  }

  statement {
    sid       = "SsmSendCommandDocument"
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript"]
  }

  statement {
    sid = "SsmReadCommandResults"
    actions = [
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations",
      "ssm:ListCommands",
      "ec2:DescribeInstances",
    ]
    resources = ["*"]
  }

  statement {
    sid     = "RdsSnapshot"
    actions = ["rds:CreateDBSnapshot", "rds:AddTagsToResource"]
    resources = [
      "arn:aws:rds:${var.aws_region}:${var.aws_account_id}:db:${local.name_prefix}-*",
      "arn:aws:rds:${var.aws_region}:${var.aws_account_id}:snapshot:${local.name_prefix}-*",
    ]
  }

  statement {
    sid       = "RdsDescribe"
    actions   = ["rds:DescribeDBInstances", "rds:DescribeDBSnapshots"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "${local.name_prefix}-deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
