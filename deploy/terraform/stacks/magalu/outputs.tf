locals {
  db_address = var.create_database ? try(data.mgc_dbaas_instance.this[0].addresses[0].address, "") : ""
  bucket     = var.create_bucket ? mgc_object_storage_buckets.media[0].bucket : ""
}

output "cluster_name" {
  value = local.create_cluster ? mgc_kubernetes_cluster.this[0].name : var.existing_cluster_id
}

output "kubeconfig" {
  value     = data.mgc_kubernetes_cluster_kubeconfig.this.kubeconfig
  sensitive = true
}

output "database_url" {
  value = var.create_database ? (
    "postgresql+psycopg://openoju:${random_password.db[0].result}@${local.db_address}:5432/openoju"
  ) : ""
  sensitive = true
}

output "database_host" {
  value = local.db_address
}

output "bucket" {
  value = local.bucket
}

output "s3_endpoint" {
  value = "https://${var.region}.magaluobjects.com"
}

output "s3_region" {
  value = var.region
}

output "s3_access_key" {
  value     = var.mgc_key_pair_id
  sensitive = true
}

output "s3_secret_key" {
  value     = var.mgc_key_pair_secret
  sensitive = true
}

output "service_account_annotations" {
  value = {}
}

output "kubeconfig_hint" {
  value = "terraform output -raw kubeconfig > ~/.kube/openoju-${var.environment}.yaml"
}
