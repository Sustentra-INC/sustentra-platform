output "app_host_instance_id" {
  value = aws_instance.app_host.id
}

output "app_host_public_ip" {
  description = "Point the DNS A record for app_domain at this IP."
  value       = aws_eip.app_host.public_ip
}

output "app_domain" {
  value = var.app_domain
}

output "dns_record_managed_by_terraform" {
  value = var.route53_zone_id != ""
}

output "ssm_session_command" {
  value = "aws ssm start-session --target ${aws_instance.app_host.id} --region ${var.aws_region}"
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "For RDS (MVP-3)."
  value       = aws_subnet.private[*].id
}
