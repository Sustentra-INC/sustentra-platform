variable "project" {
  description = "Project name, used as the first part of every resource name."
  type        = string
  default     = "sustentra"
}

variable "environment" {
  description = "Environment name (e.g. prod, staging). Used in the name prefix: <project>-<environment>-..."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.environment))
    error_message = "environment must be lowercase letters, digits or dashes (2-16 chars)."
  }
}

variable "aws_region" {
  description = "AWS region for all regional resources."
  type        = string
}

variable "aws_account_id" {
  description = "The only AWS account this config is allowed to touch."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to assume the CI roles."
  type        = string
  default     = "Sustentra-INC/sustentra-platform"
}

variable "github_branch" {
  description = "Branch whose workflows may assume the CI roles."
  type        = string
  default     = "main"
}

variable "github_environment" {
  description = "GitHub Actions environment whose jobs may assume the CI roles."
  type        = string
  default     = "production"
}

variable "create_github_oidc_provider" {
  description = "The GitHub OIDC provider is account-wide. Create it in the first environment only; set false for any additional environment in the same account."
  type        = bool
  default     = true
}

variable "ecr_repositories" {
  description = "Short names of the ECR repositories to create (prefixed with <project>-<environment>-)."
  type        = list(string)
  default     = ["api", "web"]
}

variable "ecr_keep_last_images" {
  description = "How many images to keep per ECR repository."
  type        = number
  default     = 10
}
