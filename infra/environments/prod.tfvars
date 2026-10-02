environment    = "prod"
aws_region     = "us-east-1"
aws_account_id = "012751249540"

# MVP-2 - DNS for sustentra.com is on Cloudflare: add the A record there by hand
# (DNS only / grey cloud): A record "app" -> app_host_public_ip.
app_domain      = "app.sustentra.com"
route53_zone_id = "" # empty: DNS is managed in Cloudflare, not Route 53
