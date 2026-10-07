# Audit Log Query Examples

## Synthetic Filtered Two-Page Example

Endpoint:
- GET /api/v1/orgs/{org_id}/audit-logs

Filters used in this example:
- event_type=login_success
- user_id=aaaaaaaa-2222-0000-0000-000000000021
- from_date=2026-08-01
- to_date=2026-08-31

Page 1 request:

```http
GET /api/v1/orgs/aaaaaaaa-0000-0000-0000-000000000021/audit-logs?event_type=login_success&user_id=aaaaaaaa-2222-0000-0000-000000000021&from_date=2026-08-01&to_date=2026-08-31
```

Page 1 response:

```json
{
  "items": [
    {
      "id": "7f5f1f0d-3f17-4dc1-b4ec-b76c09d4b27f",
      "org_id": "aaaaaaaa-0000-0000-0000-000000000021",
      "actor_user_id": "aaaaaaaa-2222-0000-0000-000000000021",
      "actor_role": "org_member",
      "actor_email": "member.alpha@test",
      "event_type": "login_success",
      "target_type": "session",
      "target_id": "f60d4655-9752-4d57-986f-53bfadbb48c0",
      "request_id": "req-001",
      "ip_address": "203.0.113.10",
      "user_agent": "Mozilla/5.0",
      "metadata": {
        "method": "otp"
      },
      "created_at": "2026-08-18T16:05:21+00:00"
    }
  ],
  "next_cursor": "eyJjcmVhdGVkX2F0IjoiMjAyNi0wOC0xOFQxNjowNToyMSswMDowMCIsImV2ZW50X3R5cGUiOiJsb2dpbl9zdWNjZXNzIiwiZnJvbV9kYXRlIjoiMjAyNi0wOC0wMSIsImlkIjoiN2Y1ZjFmMGQtM2YxNy00ZGMxLWI0ZWMtYjc2YzA5ZDRiMjdmIiwib3JnX2lkIjoiYWFhYWFhYWEtMDAwMC0wMDAwLTAwMDAtMDAwMDAwMDAwMDIxIiwidG9fZGF0ZSI6IjIwMjYtMDgtMzEiLCJ1c2VyX2lkIjoiYWFhYWFhYWEtMjIyMi0wMDAwLTAwMDAtMDAwMDAwMDAwMDIxIiwidiI6MX0"
}
```

Page 2 request (same filters plus cursor from page 1):

```http
GET /api/v1/orgs/aaaaaaaa-0000-0000-0000-000000000021/audit-logs?event_type=login_success&user_id=aaaaaaaa-2222-0000-0000-000000000021&from_date=2026-08-01&to_date=2026-08-31&cursor=eyJjcmVhdGVkX2F0IjoiMjAyNi0wOC0xOFQxNjowNToyMSswMDowMCIsImV2ZW50X3R5cGUiOiJsb2dpbl9zdWNjZXNzIiwiZnJvbV9kYXRlIjoiMjAyNi0wOC0wMSIsImlkIjoiN2Y1ZjFmMGQtM2YxNy00ZGMxLWI0ZWMtYjc2YzA5ZDRiMjdmIiwib3JnX2lkIjoiYWFhYWFhYWEtMDAwMC0wMDAwLTAwMDAtMDAwMDAwMDAwMDIxIiwidG9fZGF0ZSI6IjIwMjYtMDgtMzEiLCJ1c2VyX2lkIjoiYWFhYWFhYWEtMjIyMi0wMDAwLTAwMDAtMDAwMDAwMDAwMDIxIiwidiI6MX0
```

Page 2 response:

```json
{
  "items": [
    {
      "id": "69af0b73-11af-4970-8d90-0a67e77cc887",
      "org_id": "aaaaaaaa-0000-0000-0000-000000000021",
      "actor_user_id": "aaaaaaaa-2222-0000-0000-000000000021",
      "actor_role": "org_member",
      "actor_email": "member.alpha@test",
      "event_type": "login_success",
      "target_type": "session",
      "target_id": "f0d95575-df6a-48f2-b5ad-a5351b7c0f15",
      "request_id": "req-002",
      "ip_address": "203.0.113.11",
      "user_agent": "Mozilla/5.0",
      "metadata": {
        "method": "otp"
      },
      "created_at": "2026-08-18T15:57:04+00:00"
    }
  ],
  "next_cursor": null
}
```

Notes:
- The cursor is opaque to clients; treat it as an implementation detail.
- Page 2 must reuse exactly the same org_id and filter set as page 1.
- Ordering is keyset-based: created_at DESC, id DESC.
