variable "project_name" {
  description = "Name of the CI runner Droplet and its firewall."
  type        = string
  default     = "agentforge-ci-runner"
}

variable "region" {
  description = "DigitalOcean region slug (same as the demo host)."
  type        = string
  default     = "sfo3"
}

variable "droplet_size" {
  description = "Smallest Basic Droplet: 1 vCPU, 1 GB, 25 GB disk, $6/month. Enough for the lint and pytest jobs."
  type        = string
  default     = "s-1vcpu-1gb"
}

variable "droplet_image" {
  description = "DigitalOcean base image slug."
  type        = string
  default     = "ubuntu-24-04-x64"
}

variable "deployer_ssh_key_name" {
  description = "Name of the SSH key already registered on the account by the demo-host Terraform (a key can be registered only once per account)."
  type        = string
  default     = "agentforge-openemr-smoke-deployer"
}

variable "allowed_ssh_cidrs" {
  description = "Exact source CIDRs allowed to SSH (share terraform.tfvars with the demo host via -var-file=../terraform.tfvars)."
  type        = list(string)

  validation {
    condition = (
      length(var.allowed_ssh_cidrs) > 0 &&
      !contains(var.allowed_ssh_cidrs, "0.0.0.0/0") &&
      !contains(var.allowed_ssh_cidrs, "::/0")
    )
    error_message = "Provide at least one restricted SSH CIDR; world-open SSH is intentionally rejected."
  }
}

variable "gitlab_url" {
  description = "GitLab instance the runner polls (outbound only)."
  type        = string
  default     = "https://labs.gauntletai.com"
}
