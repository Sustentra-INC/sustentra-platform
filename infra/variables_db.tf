variable "db_engine_version" {
  description = "PostgreSQL major version (minor versions auto-upgrade)."
  type        = string
  default     = "16"
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  description = "Initial gp3 storage (GiB)."
  type        = number
  default     = 20
}

variable "db_max_allocated_storage_gb" {
  description = "Storage autoscaling ceiling (GiB)."
  type        = number
  default     = 100
}

variable "db_multi_az" {
  description = "Run a standby in a second AZ (roughly doubles DB cost)."
  type        = bool
  default     = false
}

variable "db_name" {
  description = "Database name."
  type        = string
  default     = "sustentra"
}

variable "db_master_username" {
  description = "RDS master user (used only for migrations)."
  type        = string
  default     = "sustentra_admin"
}

variable "db_app_username" {
  description = "Least-privilege application user (created by migration DB-001)."
  type        = string
  default     = "app_user"
}

variable "db_max_connections" {
  description = "max_connections of the RDS instance (check with SHOW max_connections;). db.t4g.micro is about 80. Used for the 80% connections alarm."
  type        = number
  default     = 80
}
