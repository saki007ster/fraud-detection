variable "environment" {
  type        = string
  description = "Environment name (e.g. dev, prod)"
  default     = "dev3"
}

variable "location" {
  type        = string
  description = "Azure region"
  default     = "centralus"
}

variable "app_name" {
  type        = string
  description = "Base application name"
  default     = "fraudagent"
}

variable "admin_object_id" {
  type        = string
  description = "Object ID of the user/SP running Terraform for Key Vault initial access"
}

# The actual secrets will be populated externally or fetched from elsewhere
variable "azure_ai_api_key" {
  type        = string
  description = "API Key for Azure AI Foundry"
  sensitive   = true
}

variable "azure_ai_endpoint" {
  type        = string
  description = "Endpoint URI for Azure AI Foundry"
}
