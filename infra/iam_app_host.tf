# Instance role for the app host (least privilege):
#   ECR pull, ssm:GetParameter on /<env>/*, ses:SendEmail from the verified
#   identity, CloudWatch Logs write, plus the AWS-managed SSM core policy
#   required for Session Manager and SSM SendCommand from the deploy role.

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app_host" {
  name               = "${local.name_prefix}-app-host"
  description        = "EC2 app host instance role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "app_host_ssm_core" {
  role       = aws_iam_role.app_host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "app_host" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [for repo in aws_ecr_repository.app : repo.arn]
  }

  statement {
    sid     = "ReadAppParameters"
    actions = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${var.aws_account_id}:parameter/${var.environment}",
      "arn:aws:ssm:${var.aws_region}:${var.aws_account_id}:parameter/${var.environment}/*",
    ]
  }

  # SecureString parameters encrypted with the default aws/ssm key.
  statement {
    sid       = "DecryptAppParameters"
    actions   = ["kms:Decrypt"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.aws_region}.amazonaws.com"]
    }
  }

  statement {
    sid       = "CloudWatchLogsWrite"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }

  # SES v2 SendEmail is authorized against both the identity and the configuration set.
  statement {
    sid     = "SendEmailFromVerifiedIdentity"
    actions = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = [
      aws_sesv2_email_identity.domain.arn,
      aws_sesv2_configuration_set.main.arn,
    ]

    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [local.ses_from_address]
    }
  }
}

resource "aws_iam_role_policy" "app_host" {
  name   = "${local.name_prefix}-app-host"
  role   = aws_iam_role.app_host.id
  policy = data.aws_iam_policy_document.app_host.json
}

resource "aws_iam_instance_profile" "app_host" {
  name = "${local.name_prefix}-app-host"
  role = aws_iam_role.app_host.name
}
