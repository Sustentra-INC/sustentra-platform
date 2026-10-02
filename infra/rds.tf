# RDS PostgreSQL 16 in the private subnets (no internet route).
# Reachable only from the app host security group on 5432; SSL enforced.

resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "${local.name_prefix}-db" }
}

resource "aws_security_group" "db" {
  name        = "${local.name_prefix}-db"
  description = "RDS PostgreSQL: 5432 from the app host only"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-db" }
}

resource "aws_vpc_security_group_ingress_rule" "db_from_app_host" {
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from the app host"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.app_host.id
}

resource "aws_db_parameter_group" "postgres16" {
  name        = "${local.name_prefix}-postgres16"
  family      = "postgres16"
  description = "Sustentra: SSL required, row-level security on"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "row_security"
    value = "on"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "random_password" "db_master" {
  length  = 40
  special = false # URL-safe: used inside the connection string
}

resource "aws_db_instance" "main" {
  identifier = "${local.name_prefix}-db"

  engine                     = "postgres"
  engine_version             = var.db_engine_version
  auto_minor_version_upgrade = true
  instance_class             = var.db_instance_class

  db_name  = var.db_name
  username = var.db_master_username
  password = random_password.db_master.result
  port     = 5432

  allocated_storage     = var.db_allocated_storage_gb
  max_allocated_storage = var.db_max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = var.db_multi_az
  parameter_group_name   = aws_db_parameter_group.postgres16.name
  ca_cert_identifier     = "rds-ca-rsa2048-g1"

  backup_retention_period   = 7
  backup_window             = "08:00-09:00" # UTC (~1am Pacific)
  maintenance_window        = "sun:09:30-sun:10:30"
  copy_tags_to_snapshot     = true
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name_prefix}-db-final"

  enabled_cloudwatch_logs_exports = ["postgresql"]

  apply_immediately = false

  tags = { Name = "${local.name_prefix}-db" }
}
