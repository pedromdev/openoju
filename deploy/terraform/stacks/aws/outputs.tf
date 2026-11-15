output "cluster_name" {
  value = local.create_cluster ? module.k8s[0].cluster_name : var.existing_cluster_name
}

output "cluster_endpoint" {
  value = local.create_cluster ? module.k8s[0].cluster_endpoint : ""
}

output "database_url" {
  value     = module.deps.database_url
  sensitive = true
}

output "database_host" {
  value = module.deps.database_host
}

output "bucket" {
  value = module.deps.bucket
}

output "service_account_annotations" {
  value = module.deps.service_account_annotations
}

output "region" {
  value = var.region
}

output "kubeconfig_command" {
  value = "aws eks update-kubeconfig --name ${local.create_cluster ? module.k8s[0].cluster_name : var.existing_cluster_name} --region ${var.region}"
}
