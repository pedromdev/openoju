locals {
  create_cluster = var.cluster_mode == "create"
  name           = "openoju-${var.environment}"
  location       = var.region
  ksa            = "${var.release_name}-openoju"
}

resource "azurerm_resource_group" "this" {
  name     = "${local.name}-rg"
  location = local.location
}

resource "azurerm_virtual_network" "this" {
  name                = "${local.name}-vnet"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  address_space       = ["10.60.0.0/16"]
}

resource "azurerm_subnet" "aks" {
  name                 = "${local.name}-aks"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.60.0.0/20"]
}

resource "azurerm_kubernetes_cluster" "this" {
  count = local.create_cluster ? 1 : 0

  name                = local.name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  dns_prefix          = local.name
  kubernetes_version  = var.cluster_version

  default_node_pool {
    name           = "system"
    node_count     = var.system_node_count
    vm_size        = var.system_node_vm_size
    vnet_subnet_id = azurerm_subnet.aks.id
    node_labels = {
      "openoju.io/pool" = "system"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin = "azure"
    network_policy = "calico"
  }

  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  node_provisioning_profile {
    mode = "Manual"
  }
}

resource "azurerm_kubernetes_cluster_node_pool" "app" {
  count = local.create_cluster ? 1 : 0

  name                  = "app"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.this[0].id
  vm_size               = var.node_vm_size
  node_count            = var.node_count
  mode                  = "User"
  vnet_subnet_id        = azurerm_subnet.aks.id

  node_labels = {
    "openoju.io/pool" = "app"
  }
}

resource "random_password" "db" {
  count   = var.create_database ? 1 : 0
  length  = 24
  special = false
}

resource "azurerm_postgresql_flexible_server" "this" {
  count = var.create_database ? 1 : 0

  name                   = "${local.name}-pg"
  resource_group_name    = azurerm_resource_group.this.name
  location               = azurerm_resource_group.this.location
  version                = "16"
  administrator_login    = "openoju"
  administrator_password = random_password.db[0].result
  storage_mb             = var.db_storage_mb
  sku_name               = var.db_instance_class
  zone                   = "1"

  public_network_access_enabled = true

  lifecycle {
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  count = var.create_database ? 1 : 0

  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.this[0].id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_database" "openoju" {
  count = var.create_database ? 1 : 0

  name      = "openoju"
  server_id = azurerm_postgresql_flexible_server.this[0].id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "${local.name}-app"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
}

resource "azurerm_federated_identity_credential" "app" {
  count = local.create_cluster ? 1 : 0

  name                      = "${local.name}-app"
  user_assigned_identity_id = azurerm_user_assigned_identity.app.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = azurerm_kubernetes_cluster.this[0].oidc_issuer_url
  subject                   = "system:serviceaccount:${var.namespace}:${local.ksa}"
}

data "azurerm_container_registry" "existing" {
  count               = var.existing_acr_name == "" ? 0 : 1
  name                = var.existing_acr_name
  resource_group_name = var.existing_acr_resource_group != "" ? var.existing_acr_resource_group : azurerm_resource_group.this.name
}

resource "azurerm_role_assignment" "acr_pull" {
  count = var.existing_acr_name == "" || !local.create_cluster ? 0 : 1

  scope                = data.azurerm_container_registry.existing[0].id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.this[0].kubelet_identity[0].object_id
}
