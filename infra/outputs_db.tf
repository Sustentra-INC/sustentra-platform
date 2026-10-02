output "db_endpoint" {
  value = aws_db_instance.main.address
}

output "db_identifier" {
  value = aws_db_instance.main.identifier
}

output "app_parameter_names" {
  value = [
    aws_ssm_parameter.db_migration_url.name,
    aws_ssm_parameter.db_app_url.name,
    aws_ssm_parameter.otp_hmac_secret.name,
  ]
}
