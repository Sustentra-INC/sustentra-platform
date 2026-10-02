# Amazon SES: verified sending domain (DKIM + custom MAIL FROM for SPF + DMARC),
# a configuration set that publishes bounces/complaints to SNS, and
# CloudWatch alarms on the account's bounce and complaint rates.
#
# DNS for sustentra.com is on Cloudflare, so Terraform does NOT create the DNS
# records - it outputs them (output "ses_dns_records") for you to add by hand.
#
# Sending domain defaults to the app domain (e.g. app.sustentra.com) so the
# Microsoft 365 email records on the root sustentra.com are never touched.

locals {
  ses_domain       = var.ses_domain != "" ? var.ses_domain : var.app_domain
  ses_mail_from    = "bounce.${local.ses_domain}"
  ses_from_address = "${var.ses_from_local_part}@${local.ses_domain}"
}

# ---------------------------------------------------------------------------
# Events: bounces and complaints -> SNS -> email
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "ses_events" {
  name = "${local.name_prefix}-ses-events"
}

data "aws_iam_policy_document" "ses_events_topic" {
  statement {
    sid       = "AllowSesPublish"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.ses_events.arn]

    principals {
      type        = "Service"
      identifiers = ["ses.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
  }

  statement {
    sid       = "AllowCloudWatchAlarms"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.ses_events.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
  }
}

resource "aws_sns_topic_policy" "ses_events" {
  arn    = aws_sns_topic.ses_events.arn
  policy = data.aws_iam_policy_document.ses_events_topic.json
}

# AWS sends a confirmation email; the subscription is active only after you
# click "Confirm subscription" in it.
resource "aws_sns_topic_subscription" "ses_events_email" {
  for_each = toset(var.alert_emails)

  topic_arn = aws_sns_topic.ses_events.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_sesv2_configuration_set" "main" {
  configuration_set_name = "${local.name_prefix}-default"

  delivery_options {
    tls_policy = "REQUIRE"
  }

  reputation_options {
    reputation_metrics_enabled = true
  }

  sending_options {
    sending_enabled = true
  }

  suppression_options {
    suppressed_reasons = ["BOUNCE", "COMPLAINT"]
  }
}

resource "aws_sesv2_configuration_set_event_destination" "sns" {
  configuration_set_name = aws_sesv2_configuration_set.main.configuration_set_name
  event_destination_name = "bounces-and-complaints-to-sns"

  event_destination {
    enabled              = true
    matching_event_types = ["BOUNCE", "COMPLAINT"]

    sns_destination {
      topic_arn = aws_sns_topic.ses_events.arn
    }
  }

  depends_on = [aws_sns_topic_policy.ses_events]
}

# ---------------------------------------------------------------------------
# Sending domain identity
# ---------------------------------------------------------------------------

resource "aws_sesv2_email_identity" "domain" {
  email_identity         = local.ses_domain
  configuration_set_name = aws_sesv2_configuration_set.main.configuration_set_name

  dkim_signing_attributes {
    next_signing_key_length = "RSA_2048_BIT"
  }
}

# Custom MAIL FROM (bounce.<domain>) so SPF passes *and* aligns with the From domain.
resource "aws_sesv2_email_identity_mail_from_attributes" "domain" {
  email_identity         = aws_sesv2_email_identity.domain.email_identity
  mail_from_domain       = local.ses_mail_from
  behavior_on_mx_failure = "USE_DEFAULT_VALUE"
}

# Sandbox fallback: while production access is pending, SES only delivers to
# verified addresses. Each address here gets a verification email from AWS.
resource "aws_sesv2_email_identity" "sandbox_recipient" {
  for_each = toset(var.ses_sandbox_recipients)

  email_identity = each.value
}

# ---------------------------------------------------------------------------
# Reputation alarms (account-level SES metrics)
# AWS reviews accounts at 5% bounce / 0.1% complaint; we alert well below that.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ses_bounce_rate" {
  alarm_name          = "${local.name_prefix}-ses-bounce-rate"
  alarm_description   = "SES bounce rate above ${var.ses_bounce_rate_threshold * 100}% (AWS review starts at 5%)"
  namespace           = "AWS/SES"
  metric_name         = "Reputation.BounceRate"
  statistic           = "Maximum"
  period              = 3600
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = var.ses_bounce_rate_threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ses_events.arn]
  ok_actions          = [aws_sns_topic.ses_events.arn]
}

resource "aws_cloudwatch_metric_alarm" "ses_complaint_rate" {
  alarm_name          = "${local.name_prefix}-ses-complaint-rate"
  alarm_description   = "SES complaint rate above ${var.ses_complaint_rate_threshold * 100}% (AWS review starts at 0.1%)"
  namespace           = "AWS/SES"
  metric_name         = "Reputation.ComplaintRate"
  statistic           = "Maximum"
  period              = 3600
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = var.ses_complaint_rate_threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ses_events.arn]
  ok_actions          = [aws_sns_topic.ses_events.arn]
}
