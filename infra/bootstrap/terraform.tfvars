# Engineers allowed to read/write Terraform state (MVP-3).
# Get your ARN with:  aws sts get-caller-identity --profile sustentra --query Arn
# When this list is non-empty, everyone else (except the CI terraform roles and
# the account root) is denied access to the state bucket.
state_bucket_engineer_arns = [
  "arn:aws:iam::012751249540:user/Jerome",
  # OPS-002: add the client admin BEFORE the laptop key is removed, or only the
  # account root can reach the state. See infra/README.md "Hand-over to CI".
  # "arn:aws:iam::012751249540:user/<client-admin>",
]
