output "resource_group_name" {
  description = "The name of the Resource Group"
  value       = azurerm_resource_group.main.name
}

output "key_vault_uri" {
  description = "The URI of the Key Vault"
  value       = azurerm_key_vault.kv.vault_uri
}

output "storage_account_name" {
  description = "The name of the ADLS Gen2 Storage Account"
  value       = azurerm_storage_account.sa.name
}

output "databricks_workspace_url" {
  description = "The URL of the Databricks workspace"
  value       = jsondecode(azapi_resource.databricks_workspace.output).properties.workspaceUrl
}

output "agent_app_url" {
  description = "The URL of the FastAPI agent"
  value       = "https://${azurerm_linux_web_app.agent_app.default_hostname}"
}

output "managed_identity_client_id" {
  description = "Client ID of the User Assigned Managed Identity"
  value       = azurerm_user_assigned_identity.agent_identity.client_id
}
