# Single EC2 host running Docker Compose (caddy + web + api).
# t3.small, Elastic IP, encrypted gp3, IMDSv2 only, SSM Session Manager, no key pair, no port 22.

data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_security_group" "app_host" {
  name        = "${local.name_prefix}-app-host"
  description = "App host: inbound HTTP/HTTPS only"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-app-host" }
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.app_host.id
  description       = "HTTP (redirects to HTTPS, ACME challenge)"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.app_host.id
  description       = "HTTPS"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

# Outbound is needed for ECR pulls, SSM, CloudWatch, SES, Let's Encrypt and OS updates.
resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.app_host.id
  description       = "All outbound"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.project}/${var.environment}/app"
  retention_in_days = var.log_retention_days
}

resource "aws_instance" "app_host" {
  ami                    = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = var.app_instance_type
  subnet_id              = aws_subnet.public[0].id
  vpc_security_group_ids = [aws_security_group.app_host.id]
  iam_instance_profile   = aws_iam_instance_profile.app_host.name
  # No key_name: shell access is via SSM Session Manager only.

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 2          # lets containers reach IMDS for the instance role
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.app_root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/app_host_user_data.sh.tftpl", {
    aws_region      = var.aws_region
    log_group       = aws_cloudwatch_log_group.app.name
    compose_version = var.docker_compose_version
    app_domain      = var.app_domain
    ecr_registry    = "${var.aws_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
    name_prefix     = local.name_prefix
  })
  user_data_replace_on_change = false

  tags = { Name = "${local.name_prefix}-app-host" }

  lifecycle {
    # A newer AL2023 AMI should not silently replace the running host.
    ignore_changes = [ami, user_data]
  }
}

resource "aws_eip" "app_host" {
  domain   = "vpc"
  instance = aws_instance.app_host.id

  tags = { Name = "${local.name_prefix}-app-host" }

  depends_on = [aws_internet_gateway.main]
}

# DNS: created here only if the domain's hosted zone is in Route 53 in this account.
# Otherwise add an A record <app_domain> -> app_host_public_ip at the DNS provider.
resource "aws_route53_record" "app" {
  count = var.route53_zone_id == "" ? 0 : 1

  zone_id = var.route53_zone_id
  name    = var.app_domain
  type    = "A"
  ttl     = 300
  records = [aws_eip.app_host.public_ip]
}
