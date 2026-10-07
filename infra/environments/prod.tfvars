environment    = "prod"
aws_region     = "us-east-1"
aws_account_id = "012751249540"

# MVP-2 - DNS for sustentra.com is on Cloudflare: add the A record there by hand
# (DNS only / grey cloud): A record "app" -> app_host_public_ip.
app_domain      = "app.sustentra.com"
route53_zone_id = "" # empty: DNS is managed in Cloudflare, not Route 53

# MVP-4 - SES. Sends as no-reply@<app_domain>; DNS records come from
# `terraform output ses_dns_records` and are added in Cloudflare by hand.
alert_emails           = ["dev.sustentra@gmail.com"]  # e.g. ["ops@sustentra.com"] - receives bounce/complaint/alarm emails
ses_sandbox_recipients = [] # OPS-001: SES production access granted; no sandbox recipients needed

# Live instance is db.t3.micro (db.t4g.micro had no capacity at creation)
db_instance_class = "db.t3.micro"
