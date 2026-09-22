variable "project_name" {
  description = "Name prefix for the short-lived DigitalOcean resources."
  type        = string
  default     = "agentforge-openemr-smoke"
}

variable "region" {
  description = "DigitalOcean region slug."
  type        = string
  default     = "sfo3"
}

variable "droplet_size" {
  description = "Droplet size slug. Week 2 uses four dedicated vCPUs and 8 GiB RAM."
  type        = string
  default     = "c-4"
}

variable "droplet_image" {
  description = "DigitalOcean base image slug."
  type        = string
  default     = "ubuntu-24-04-x64"
}

variable "ssh_public_key_path" {
  description = "Local public key installed for the deployer account."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"

  validation {
    condition     = fileexists(pathexpand(var.ssh_public_key_path))
    error_message = "ssh_public_key_path must point to an existing public key."
  }
}

variable "allowed_ssh_cidrs" {
  description = "Exact source CIDRs allowed to SSH, normally your current public IPv4 with /32."
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
