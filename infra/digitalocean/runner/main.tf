# A dedicated GitLab project runner for the AgentForge repository.
#
# Why a separate host: a runner executes whatever .gitlab-ci.yml says at the
# commit being built and needs the Docker socket, so it must not share a
# machine with the demo stack (secrets, PHI-shaped demo data) or with the
# owner's workstation. This Droplet holds nothing but the runner; if it is
# ever suspect, destroy it and register a new one.
#
# Registration is a separate step (register.sh): the runner authentication
# token never enters Terraform state, cloud-init user data, or a shell history.

data "digitalocean_ssh_key" "deployer" {
  name = var.deployer_ssh_key_name
}

resource "digitalocean_droplet" "runner" {
  name       = var.project_name
  region     = var.region
  size       = var.droplet_size
  image      = var.droplet_image
  monitoring = true
  backups    = false
  ipv6       = false
  ssh_keys   = [data.digitalocean_ssh_key.deployer.fingerprint]
  tags       = ["agentforge", "ci-runner"]

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {})
}

resource "digitalocean_firewall" "runner" {
  name        = "${var.project_name}-firewall"
  droplet_ids = [digitalocean_droplet.runner.id]

  # SSH only from the owner's address; the runner itself needs no inbound port.
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = var.allowed_ssh_cidrs
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
