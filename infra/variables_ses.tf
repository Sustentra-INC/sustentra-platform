variable "ses_domain" {
  description = "Domain SES sends from. Empty = use app_domain (e.g. app.sustentra.com)."
  type        = string
  default     = ""
}

variable "ses_from_local_part" {
  description = "Local part of the From address, e.g. no-reply -> no-reply@<ses_domain>."
  type        = string
  default     = "no-reply"
}

variable "dmarc_policy" {
  description = "DMARC policy for the sending domain: quarantine or reject."
  type        = string
  default     = "quarantine"

  validation {
    condition     = contains(["quarantine", "reject"], var.dmarc_policy)
    error_message = "dmarc_policy must be quarantine or reject."
  }
}

variable "alert_emails" {
  description = "Email addresses subscribed to SES bounce/complaint events and alarms (each must confirm the AWS subscription email)."
  type        = list(string)
  default     = []
}

variable "ses_sandbox_recipients" {
  description = "Developer addresses to verify as recipients while SES is still in the sandbox."
  type        = list(string)
  default     = []
}

variable "ses_bounce_rate_threshold" {
  description = "Alarm when the account bounce rate reaches this fraction (0.02 = 2%)."
  type        = number
  default     = 0.02
}

variable "ses_complaint_rate_threshold" {
  description = "Alarm when the account complaint rate reaches this fraction (0.0005 = 0.05%)."
  type        = number
  default     = 0.0005
}
