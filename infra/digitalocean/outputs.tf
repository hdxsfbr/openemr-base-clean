output "droplet_id" {
  description = "DigitalOcean Droplet ID."
  value       = digitalocean_droplet.app.id
}

output "ipv4_address" {
  description = "Public IPv4 address used by the deployment script."
  value       = digitalocean_droplet.app.ipv4_address
}

output "smoke_hostname" {
  description = "Disposable sslip.io hostname for a TLS smoke test; replace it with owned DNS for the evaluator deployment."
  value       = "openemr-${replace(digitalocean_droplet.app.ipv4_address, ".", "-")}.sslip.io"
}

output "estimated_hourly_usd" {
  description = "Known compute-only hourly rate for supported smoke-test sizes; null for an unlisted size."
  value       = lookup(local.known_hourly_prices, var.droplet_size, null)
}

output "ssh_command" {
  description = "Command for connecting after cloud-init completes."
  value       = "ssh deployer@${digitalocean_droplet.app.ipv4_address}"
}
