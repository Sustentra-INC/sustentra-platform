variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "app_domain" {
  description = "Public hostname of the app (e.g. app.example.com). Caddy requests the HTTPS certificate for this name."
  type        = string
}

variable "route53_zone_id" {
  description = "Route 53 hosted zone ID for app_domain. Leave empty if DNS is managed elsewhere (then add the A record by hand)."
  type        = string
  default     = ""
}

variable "ses_identity" {
  description = "Verified SES identity (domain or email) the app may send from. Empty = no SES permission yet (set by MVP-4)."
  type        = string
  default     = ""
}

variable "app_instance_type" {
  description = "EC2 instance type for the app host."
  type        = string
  default     = "t3.small"
}

variable "app_root_volume_gb" {
  description = "Size of the encrypted gp3 root volume (GiB)."
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for container logs."
  type        = number
  default     = 30
}

variable "docker_compose_version" {
  description = "Docker Compose plugin release installed on the host."
  type        = string
  default     = "v2.29.7"
}
