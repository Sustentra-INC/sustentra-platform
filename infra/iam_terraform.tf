# "terraform" role: used by the infra pipeline to plan/apply this config
# (network, EC2, RDS, SES, monitoring in MVP-2..MVP-6).
#
# PowerUserAccess covers every non-IAM service. IAM is limited to resources
# named "<project>-<environment>-*" plus the GitHub OIDC provider.
# Note: because this role can edit roles in its own prefix, it can effectively
# grant itself more rights inside that prefix. That is inherent to letting CI
# manage IAM; protect it with the GitHub "production" environment rules.

resource "aws_iam_role" "terraform" {
  name                 = "${local.name_prefix}-terraform"
  description          = "GitHub Actions Terraform role (infrastructure changes)"
  assume_role_policy   = data.aws_iam_policy_document.github_actions_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "terraform_power_user" {
  role       = aws_iam_role.terraform.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

data "aws_iam_policy_document" "terraform_iam" {
  statement {
    sid       = "IamRead"
    actions   = ["iam:Get*", "iam:List*"]
    resources = ["*"]
  }

  statement {
    sid     = "IamManageProjectResources"
    actions = ["iam:*"]
    resources = [
      "arn:aws:iam::${var.aws_account_id}:role/${local.name_prefix}-*",
      "arn:aws:iam::${var.aws_account_id}:policy/${local.name_prefix}-*",
      "arn:aws:iam::${var.aws_account_id}:instance-profile/${local.name_prefix}-*",
      "arn:aws:iam::${var.aws_account_id}:oidc-provider/token.actions.githubusercontent.com",
    ]
  }

  statement {
    sid = "TerraformState"
    actions = [
      "s3:ListBucket",
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = [
      "arn:aws:s3:::${local.state_bucket_name}",
      "arn:aws:s3:::${local.state_bucket_name}/*",
    ]
  }
}

resource "aws_iam_role_policy" "terraform_iam" {
  name   = "${local.name_prefix}-terraform-iam"
  role   = aws_iam_role.terraform.id
  policy = data.aws_iam_policy_document.terraform_iam.json
}
