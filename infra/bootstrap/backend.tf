# Step 2 of the bootstrap (see infra/README.md):
# after the first apply, rename this file to backend.tf and run
#   terraform init -migrate-state
# so the bootstrap's own state also lives in the bucket it created.

terraform {
  backend "s3" {
    bucket       = "sustentra-tfstate-012751249540"
    key          = "bootstrap/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
