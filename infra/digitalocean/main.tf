locals {
  ssh_public_key = trimspace(file(pathexpand(var.ssh_public_key_path)))

  # Current public Basic Droplet rates recorded for the smoke-test sizes.
  known_hourly_prices = {
    "s-2vcpu-4gb" = 0.03571
    "s-4vcpu-8gb" = 0.07143
  }
}

resource "digitalocean_ssh_key" "deployer" {
  name       = "${var.project_name}-deployer"
  public_key = local.ssh_public_key
}

resource "digitalocean_droplet" "app" {
  name       = var.project_name
  region     = var.region
  size       = var.droplet_size
  image      = var.droplet_image
  monitoring = true
  backups    = false
  ipv6       = false
  ssh_keys   = [digitalocean_ssh_key.deployer.fingerprint]
  tags       = ["agentforge", "openemr", "ephemeral-smoke"]

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    ssh_public_key = local.ssh_public_key
  })
}

resource "digitalocean_firewall" "app" {
  name        = "${var.project_name}-firewall"
  droplet_ids = [digitalocean_droplet.app.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = var.allowed_ssh_cidrs
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
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

resource "digitalocean_project" "app" {
  name        = var.project_name
  description = "Ephemeral AgentForge OpenEMR deployment"
  purpose     = "Service or API"
  environment = "Development"
  resources   = [digitalocean_droplet.app.urn]
}
