output "ses_from_address" {
  value = local.ses_from_address
}

output "ses_configuration_set" {
  value = aws_sesv2_configuration_set.main.configuration_set_name
}

output "ses_events_topic_arn" {
  value = aws_sns_topic.ses_events.arn
}

# Add these in Cloudflare (sustentra.com -> DNS -> Records), proxy status "DNS only".
output "ses_dns_records" {
  description = "DNS records to create at the DNS provider for SES (DKIM, MAIL FROM/SPF, DMARC)."
  value = concat(
    [
      for token in aws_sesv2_email_identity.domain.dkim_signing_attributes[0].tokens : {
        type  = "CNAME"
        name  = "${token}._domainkey.${local.ses_domain}"
        value = "${token}.dkim.amazonses.com"
      }
    ],
    [
      {
        type  = "MX"
        name  = local.ses_mail_from
        value = "10 feedback-smtp.${var.aws_region}.amazonses.com"
      },
      {
        type  = "TXT"
        name  = local.ses_mail_from
        value = "v=spf1 include:amazonses.com -all"
      },
      {
        type  = "TXT"
        name  = "_dmarc.${local.ses_domain}"
        # Relaxed alignment: SPF passes via bounce.<domain>, DKIM via <domain>.
        value = "v=DMARC1; p=${var.dmarc_policy}; pct=100"
      },
    ],
  )
}
