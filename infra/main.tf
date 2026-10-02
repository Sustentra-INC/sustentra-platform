locals {
  # Every resource in this config is named "<project>-<environment>-<thing>",
  # e.g. sustentra-prod-deploy, sustentra-prod-api.
  name_prefix = "${var.project}-${var.environment}"

  state_bucket_name = "${var.project}-tfstate-${var.aws_account_id}"

  # GitHub OIDC "sub" claims that may assume the CI roles:
  #  - workflows running on the main branch (jobs without an environment)
  #  - jobs that declare `environment: production`
  github_oidc_subjects = [
    "repo:${var.github_repository}:ref:refs/heads/${var.github_branch}",
    "repo:${var.github_repository}:environment:${var.github_environment}",
  ]
}
