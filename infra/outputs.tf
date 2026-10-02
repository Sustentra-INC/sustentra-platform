output "github_oidc_provider_arn" {
  value = local.github_oidc_provider_arn
}

output "deploy_role_arn" {
  description = "Use in GitHub Actions: aws-actions/configure-aws-credentials role-to-assume"
  value       = aws_iam_role.deploy.arn
}

output "terraform_role_arn" {
  description = "Use in GitHub Actions: aws-actions/configure-aws-credentials role-to-assume"
  value       = aws_iam_role.terraform.arn
}

output "ecr_repository_urls" {
  value = { for name, repo in aws_ecr_repository.app : name => repo.repository_url }
}
