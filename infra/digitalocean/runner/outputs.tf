output "runner_ip" {
  value = digitalocean_droplet.runner.ipv4_address
}

output "register_hint" {
  value = "Then: ./runner/register.sh ${digitalocean_droplet.runner.ipv4_address} ~/.config/agentforge/gitlab_runner_token"
}
