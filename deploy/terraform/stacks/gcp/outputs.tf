output "cluster_name" {
  value = local.create_cluster ? google_container_cluster.this[0].name : var.existing_cluster_name
}

output "cluster_endpoint" {
  value = local.create_cluster ? google_container_cluster.this[0].endpoint : ""
}

output "database_url" {
  value = var.create_database ? (
    "postgresql+psycopg://openoju:${random_password.db[0].result}@${google_sql_database_instance.this[0].public_ip_address}:5432/openoju"
  ) : ""
  sensitive = true
}

output "database_host" {
  value = var.create_database ? google_sql_database_instance.this[0].public_ip_address : ""
}

output "bucket" {
  value = var.create_bucket ? google_storage_bucket.media[0].name : ""
}

output "s3_access_key" {
  value     = var.create_bucket ? google_storage_hmac_key.app[0].access_id : ""
  sensitive = true
}

output "s3_secret_key" {
  value     = var.create_bucket ? google_storage_hmac_key.app[0].secret : ""
  sensitive = true
}

output "s3_endpoint" {
  value = "https://storage.googleapis.com"
}

output "s3_region" {
  value = "auto"
}

output "service_account_annotations" {
  value = {
    "iam.gke.io/gcp-service-account" = google_service_account.app.email
  }
}

output "kubeconfig_command" {
  value = "gcloud container clusters get-credentials ${local.create_cluster ? google_container_cluster.this[0].name : var.existing_cluster_name} --zone ${var.zone} --project ${var.project_id}"
}

output "image_registry" {
  value = var.existing_gar_repository == "" ? "" : "${data.google_artifact_registry_repository.existing[0].location}-docker.pkg.dev/${var.project_id}/${var.existing_gar_repository}"
}
