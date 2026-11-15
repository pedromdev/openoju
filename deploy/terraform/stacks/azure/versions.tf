terraform {
  required_version = ">= 1.11.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # backend "azurerm" {
  #   resource_group_name  = "openoju-tfstate"
  #   storage_account_name = "openojutfstate"
  #   container_name       = "tfstate"
  #   key                  = "azure.tfstate"
  # }
}

provider "azurerm" {
  subscription_id = var.subscription_id

  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}
