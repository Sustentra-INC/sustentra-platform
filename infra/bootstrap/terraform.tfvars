# Engineers allowed to read/write Terraform state (MVP-3).
# Get your ARN with:  aws sts get-caller-identity --profile sustentra --query Arn
# When this list is non-empty, everyone else (except the CI terraform roles and
# the account root) is denied access to the state bucket.
state_bucket_engineer_arns = [
  "arn:aws:iam::012751249540:user/Jerome",
  # "arn:aws:iam::012751249540:user/<client-admin>", # add before applying if the client needs state access
]
