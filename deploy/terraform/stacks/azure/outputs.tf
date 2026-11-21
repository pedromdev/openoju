output "cluster_name" {
  value = local.create_cluster ? azurerm_kubernetes_cluster.this[0].name : var.existing_cluster_name
}

output "resource_group" {
  value = azurerm_resource_group.this.name
}

output "database_url" {
  value = var.create_database ? (
    "postgresql+psycopg://openoju:${random_password.db[0].result}@${azurerm_postgresql_flexible_server.this[0].fqdn}:5432/openoju"
  ) : ""
  sensitive = true
}

output "database_host" {
  value = var.create_database ? azurerm_postgresql_flexible_server.this[0].fqdn : ""
}

output "bucket" {
  value = ""
}

output "service_account_annotations" {
  value = {
    "azure.workload.identity/client-id" = azurerm_user_assigned_identity.app.client_id
  }
}

output "kubeconfig_command" {
  value = "az aks get-credentials --resource-group ${azurerm_resource_group.this.name} --name ${local.create_cluster ? azurerm_kubernetes_cluster.this[0].name : var.existing_cluster_name}"
}

output "image_registry" {
  value = var.existing_acr_name == "" ? "" : data.azurerm_container_registry.existing[0].login_server
}

output "storage_account" {
  value = azurerm_storage_account.media.name
}

output "storage_container" {
  value = azurerm_storage_container.media.name
}

output "storage_endpoint" {
  value = azurerm_storage_account.media.primary_blob_endpoint
}
