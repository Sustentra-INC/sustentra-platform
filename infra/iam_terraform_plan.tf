# Read-only "terraform-plan" role for pull requests, so every infra PR gets a
# `terraform plan` comment. It trusts only pull_request workflows from this
# repository (forks never receive OIDC tokens) and cannot change anything:
#   - AWS-managed ReadOnlyAccess (Describe/Get/List) to refresh state
#   - read the state file (plan runs with -lock=false, so no lock-file writes)
#   - decrypt SSM SecureStrings (needed to refresh aws_ssm_parameter)

data "aws_iam_policy_document" "github_pr_trust" {
  statement {
    sid     = "GitHubActionsPullRequests"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:pull_request"]
    }
  }
}

resource "aws_iam_role" "terraform_plan" {
  name                 = "${local.name_prefix}-terraform-plan"
  description          = "GitHub Actions read-only role: terraform plan on pull requests"
  assume_role_policy   = data.aws_iam_policy_document.github_pr_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "terraform_plan_read_only" {
  role       = aws_iam_role.terraform_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "terraform_plan" {
  statement {
    sid       = "ReadState"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = ["arn:aws:s3:::${local.state_bucket_name}", "arn:aws:s3:::${local.state_bucket_name}/*"]
  }

  statement {
    sid       = "DecryptSsmParameters"
    actions   = ["kms:Decrypt"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.aws_region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "terraform_plan" {
  name   = "${local.name_prefix}-terraform-plan"
  role   = aws_iam_role.terraform_plan.id
  policy = data.aws_iam_policy_document.terraform_plan.json
}

output "terraform_plan_role_arn" {
  value = aws_iam_role.terraform_plan.arn
}
