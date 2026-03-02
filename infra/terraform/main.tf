locals {
  suffix = "${var.app_name}${var.environment}"
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${local.suffix}"
  location = var.location
  tags = {
    Environment = var.environment
    Project     = "FraudDetection"
  }
}

# ─────────────────────────────────────────────────────────────
# 1. User Assigned Managed Identity (Used by App Service)
# ─────────────────────────────────────────────────────────────
resource "azurerm_user_assigned_identity" "agent_identity" {
  name                = "id-${local.suffix}-agent"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
}

# ─────────────────────────────────────────────────────────────
# 2. Key Vault (Secrets Management)
# ─────────────────────────────────────────────────────────────
resource "azurerm_key_vault" "kv" {
  name                       = "kv-${local.suffix}-${random_string.suffix.result}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  enable_rbac_authorization  = true
}

resource "random_string" "suffix" {
  length  = 4
  special = false
  upper   = false
}

data "azurerm_client_config" "current" {}

# Give the App Service Identity 'Key Vault Secrets User'
resource "azurerm_role_assignment" "kv_secret_user" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.agent_identity.principal_id
}

# Give the TF Runner 'Key Vault Secrets Officer' to provision secrets
resource "azurerm_role_assignment" "kv_secret_officer" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = var.admin_object_id
}

# Add the Azure AI Foundry Secrets
resource "azurerm_key_vault_secret" "hf_api_key" {
  name         = "azure-ai-api-key"
  value        = var.azure_ai_api_key
  key_vault_id = azurerm_key_vault.kv.id
  depends_on   = [azurerm_role_assignment.kv_secret_officer]
}

# ─────────────────────────────────────────────────────────────
# 3. Storage Account (ADLS Gen2 for Logs)
# ─────────────────────────────────────────────────────────────
resource "azurerm_storage_account" "sa" {
  name                     = "st${local.suffix}${random_string.suffix.result}"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  is_hns_enabled           = true # Essential for ADLS Gen2
  min_tls_version          = "TLS1_2"
}

resource "azurerm_storage_data_lake_gen2_filesystem" "logs" {
  name               = "logs"
  storage_account_id = azurerm_storage_account.sa.id
}

resource "azurerm_storage_data_lake_gen2_filesystem" "raw" {
  name               = "raw"
  storage_account_id = azurerm_storage_account.sa.id
}

# Give App Service Identity 'Storage Blob Data Contributor' to write logs
resource "azurerm_role_assignment" "sa_blob_contributor" {
  scope                = azurerm_storage_account.sa.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.agent_identity.principal_id
}

# ─────────────────────────────────────────────────────────────
# 4. App Service Plan & Web App (FastAPI Agent)
# ─────────────────────────────────────────────────────────────
resource "azurerm_service_plan" "asp" {
  name                = "asp-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = "B1" # Reverted to B1 for Central US deployment 
}

resource "azurerm_linux_web_app" "agent_app" {
  name                = "app-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.asp.id

  # Connect the user assigned identity
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.agent_identity.id]
  }

  site_config {
    always_on = true
    application_stack {
      docker_image_name   = "saki007ster/fraud-agent:latest"
      docker_registry_url = "https://ghcr.io" # Assuming GitHub Container Registry (placeholder)
    }
  }

  app_settings = {
    "WEBSITES_PORT"   = "8000"
    "AZURE_CLIENT_ID" = azurerm_user_assigned_identity.agent_identity.client_id
    # Key Vault references for secrets
    "AZURE_AI_API_KEY"       = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.hf_api_key.id})"
    "AZURE_AI_ENDPOINT"      = var.azure_ai_endpoint
    "ADLS_CONNECTION_STRING" = azurerm_storage_account.sa.primary_connection_string
    "CORS_ORIGINS"           = "*"
  }
}

# ─────────────────────────────────────────────────────────────
# 5. Databricks Workspace (Using AzAPI provider)
# ─────────────────────────────────────────────────────────────
resource "azapi_resource" "databricks_workspace" {
  type      = "Microsoft.Databricks/workspaces@2023-02-01"
  name      = "dbw-${local.suffix}"
  parent_id = azurerm_resource_group.main.id
  location  = azurerm_resource_group.main.location

  body = jsonencode({
    properties = {
      managedResourceGroupId = "${azurerm_resource_group.main.id}-databricks"
      parameters = {
        prepareEncryption = { value = false }
      }
    }
  })

  response_export_values = ["properties.workspaceUrl"]
}
