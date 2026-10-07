environment    = "staging"
aws_region     = "us-east-1"
aws_account_id = "012751249540"

# The GitHub OIDC provider is account-wide and already created by prod.
create_github_oidc_provider = false

# Staging CI roles trust the GitHub "staging" environment (prod uses "production").
github_environment = "staging"

# The deploy workflow builds images on pushes to the "staging" branch.
github_branch = "staging"

# Separate address range from prod (10.20.0.0/16).
vpc_cidr = "10.21.0.0/16"

# DNS for sustentra.com is on Cloudflare: add the A record there by hand
# (DNS only / grey cloud): A record "staging" -> app_host_public_ip.
app_domain      = "staging.sustentra.com"
route53_zone_id = "" # empty: DNS is managed in Cloudflare, not Route 53

# MVP-4 - SES. Sends as no-reply@<app_domain>; DNS records come from
# `terraform output ses_dns_records` and are added in Cloudflare by hand.
alert_emails           = ["dev.sustentra@gmail.com"] # e.g. ["ops@sustentra.com"] - receives bounce/complaint/alarm emails
ses_sandbox_recipients = []                          # OPS-001: SES production access granted; no sandbox recipients needed

# Same as prod: db.t4g.micro had no capacity in us-east-1
db_instance_class = "db.t3.micro"
