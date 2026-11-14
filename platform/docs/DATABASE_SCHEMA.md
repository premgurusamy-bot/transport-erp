# Database schema

PostgreSQL 16, managed by Alembic (`backend/alembic/versions`). Generated from the SQLAlchemy models - regenerate after model changes.

Conventions: UUID primary keys (except append-only logs), `created_at`/`updated_at` in UTC, money `NUMERIC(14,2)`, JSON for flexible
structured fields, foreign keys for every relationship, check constraint on voucher lines (one side, positive), partial unique
index preventing a booking/charge from being billed twice, unique business codes per financial year.

Total tables: 105

## Module: platform

### `approval_requests` — Generic maker-checker approval. The executing service re-checks status before acting.
Columns: `code` varchar NOT NULL, `kind` varchar NOT NULL, `entity` varchar NOT NULL, `entity_id` varchar NOT NULL, `title` varchar NOT NULL, `amount` numeric, `payload` json, `required_permission` varchar NOT NULL, `status` varchar NOT NULL, `maker_id` char NOT NULL, `maker_reason` text, `checker_id` char, `checker_note` text, `decided_at` datetime, `origin` varchar NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `maker_id` → `users`, `checker_id` → `users`

### `audit_log` — Hash-chained audit log: each row's hash covers its content and the previous row's hash, so any edit/deletion of history is detectable by verify_chain(). (Tamper-evident, not tamper-proof.)
Columns: `id` bigint NOT NULL, `at` datetime NOT NULL, `actor_id` char, `actor_name` varchar, `action` varchar NOT NULL, `entity` varchar NOT NULL, `entity_id` varchar, `before` json, `after` json, `reason` text, `ip` varchar, `prev_hash` varchar NOT NULL, `hash` varchar NOT NULL  

### `comm_consents`
Columns: `recipient` varchar NOT NULL, `channel` varchar NOT NULL, `opted_in` boolean NOT NULL, `source` varchar, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  

### `config_values` — Versioned business configuration with effective dates. Never updated in place: a change inserts a new version.
Columns: `key` varchar NOT NULL, `version` integer NOT NULL, `value` json, `effective_from` datetime NOT NULL, `changed_by` char, `reason` text, `created_at` datetime NOT NULL, `id` char NOT NULL  

### `documents` — Metadata for an object in encrypted object storage. Binary content lives in the object store.
Columns: `doc_type` varchar NOT NULL, `entity` varchar NOT NULL, `entity_id` varchar NOT NULL, `filename` varchar NOT NULL, `content_type` varchar NOT NULL, `size` integer NOT NULL, `sha256` varchar NOT NULL, `storage_key` varchar NOT NULL, `version` integer NOT NULL, `valid_from` datetime, `valid_to` datetime, `doc_number` varchar, `review_status` varchar NOT NULL, `extracted` json, `legal_hold` boolean NOT NULL, `captured_lat` double, `captured_lng` double, `captured_at` datetime, `uploaded_by` char, `customer_id` char, `visible_to_customer` boolean NOT NULL, `visible_to_driver` boolean NOT NULL, `deleted_at` datetime, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `uploaded_by` → `users`, `customer_id` → `customers`

### `integration_providers` — Registry of every external integration and its honest status (MOCK / SANDBOX / LIVE / DISABLED).
Columns: `kind` varchar NOT NULL, `adapter` varchar NOT NULL, `mode` varchar NOT NULL, `last_success_at` datetime, `last_error` text, `verified_live_at` datetime, `notes` text, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  

### `login_attempts`
Columns: `identifier` varchar NOT NULL, `success` boolean NOT NULL, `ip` varchar, `at` datetime NOT NULL, `id` char NOT NULL  

### `notifications` — Outbox for every outgoing message. A worker delivers via the channel adapter and records the result.
Columns: `channel` varchar NOT NULL, `template` varchar NOT NULL, `recipient` varchar NOT NULL, `user_id` char, `subject` varchar, `body` text NOT NULL, `entity` varchar, `entity_id` varchar, `status` varchar NOT NULL, `requires_approval` boolean NOT NULL, `approved_by` char, `provider` varchar, `provider_ref` varchar, `error` text, `read_at` datetime, `sent_at` datetime, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `user_id` → `users`, `approved_by` → `users`

### `number_sequences`
Columns: `series` varchar NOT NULL, `fy` varchar NOT NULL, `last` integer NOT NULL  

### `otp_challenges` — OTP is stored only as an HMAC; the plain OTP is sent via the SMS/WhatsApp adapter.
Columns: `purpose` varchar NOT NULL, `target` varchar NOT NULL, `ref_id` char, `otp_hash` varchar NOT NULL, `expires_at` datetime NOT NULL, `attempts` integer NOT NULL, `consumed_at` datetime, `created_at` datetime NOT NULL, `id` char NOT NULL  

### `roles`
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `permissions` array NOT NULL, `is_external` boolean NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  

### `sessions`
Columns: `user_id` char NOT NULL, `token_hash` varchar NOT NULL, `created_at` datetime NOT NULL, `expires_at` datetime NOT NULL, `revoked_at` datetime, `device` varchar, `ip` varchar, `scope_trip_id` char, `id` char NOT NULL  
References: `user_id` → `users`, `scope_trip_id` → `trips`

### `stored_objects` — Fallback object store inside PostgreSQL for development only (when no S3 is configured).
Columns: `key` varchar NOT NULL, `data` blob NOT NULL  

### `sync_events` — Offline events from Driver/Management apps. client_event_id makes submission idempotent.
Columns: `client_event_id` varchar NOT NULL, `device_id` varchar NOT NULL, `user_id` char NOT NULL, `event_type` varchar NOT NULL, `payload` json NOT NULL, `occurred_at` datetime NOT NULL, `received_at` datetime NOT NULL, `source` varchar NOT NULL, `status` varchar NOT NULL, `result` json  
References: `user_id` → `users`

### `tasks` — Exception / task register used by the Control Tower and SOP checklists.
Columns: `code` varchar NOT NULL, `kind` varchar NOT NULL, `severity` varchar NOT NULL, `title` varchar NOT NULL, `detail` text, `source` varchar, `entity` varchar, `entity_id` varchar, `owner_role` varchar, `assignee_id` char, `due_at` datetime, `status` varchar NOT NULL, `blocking` boolean NOT NULL, `closed_at` datetime, `closure_reason` text, `escalated` boolean NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `assignee_id` → `users`

### `temp_driver_access` — Trip-scoped, OTP-verified access for attached/market drivers. Revoked on trip completion/cancellation.
Columns: `trip_id` char NOT NULL, `driver_id` char NOT NULL, `phone` varchar NOT NULL, `expires_at` datetime NOT NULL, `revoked_at` datetime, `revoke_reason` varchar, `gps_consent_at` datetime, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `trip_id` → `trips`, `driver_id` → `drivers`

### `user_roles`
Columns: `user_id` char NOT NULL, `role_id` char NOT NULL  
References: `user_id` → `users`, `role_id` → `roles`

### `users`
Columns: `name` varchar NOT NULL, `email` varchar, `phone` varchar, `password_hash` varchar, `is_active` boolean NOT NULL, `language` varchar NOT NULL, `customer_id` char, `owner_id` char, `vendor_id` char, `driver_id` char, `employee_id` char, `access_valid_from` datetime, `access_valid_to` datetime, `access_purpose` varchar, `last_login_at` datetime, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `customer_id` → `customers`, `owner_id` → `vehicle_owners`, `vendor_id` → `vendors`, `driver_id` → `drivers`, `employee_id` → `employees`

## Module: masters

### `charge_types`
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `kind` varchar NOT NULL, `gst_applicable` boolean NOT NULL, `ledger_code` varchar, `id` char NOT NULL  

### `company_bank_accounts`
Columns: `name` varchar NOT NULL, `bank_name` varchar NOT NULL, `account_number_masked` varchar NOT NULL, `ifsc` varchar, `ledger_code` varchar NOT NULL, `is_cash` boolean NOT NULL, `opening_balance` numeric NOT NULL, `opening_date` date, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  

### `contacts`
Columns: `customer_id` char, `owner_id` char, `vendor_id` char, `name` varchar NOT NULL, `designation` varchar, `phone` varchar, `email` varchar, `whatsapp_opt_in` boolean NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `customer_id` → `customers`, `owner_id` → `vehicle_owners`, `vendor_id` → `vendors`

### `credit_profiles` — Approved credit terms. Changes go through approval and create a new effective-dated row.
Columns: `customer_id` char NOT NULL, `limit_amount` numeric NOT NULL, `credit_days` integer NOT NULL, `advance_pct` numeric NOT NULL, `deposit_amount` numeric NOT NULL, `risk_category` varchar NOT NULL, `effective_from` datetime NOT NULL, `status` varchar NOT NULL, `approved_by` char, `proposed_by` char, `reason` text, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `customer_id` → `customers`, `approved_by` → `users`, `proposed_by` → `users`

### `customer_branches`
Columns: `customer_id` char NOT NULL, `name` varchar NOT NULL, `address` text, `city` varchar, `pincode` varchar, `gstin` varchar, `lat` double, `lng` double, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `customer_id` → `customers`

### `customers` — A customer organisation = a tenant. Customer users only ever see records with their customer_id.
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `name_normalized` varchar NOT NULL, `group_name` varchar, `gstin` varchar, `pan` varchar, `billing_address` text, `state_code` varchar, `phone` varchar, `email` varchar, `status` varchar NOT NULL, `billing_cycle` varchar NOT NULL, `gst_mode` varchar NOT NULL, `source` varchar, `notes` text, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  

### `facilities` — Office, godown or partner facility. Only `verified` facilities may be offered/used for custody.
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `kind` varchar NOT NULL, `address` text, `area_sqft` numeric, `length_ft` numeric, `width_ft` numeric, `ceiling_ft` numeric, `max_vehicle_type` varchar, `operating_hours` varchar, `verified` boolean NOT NULL, `verification_notes` text, `safety_checklist` json, `partner_vendor_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `partner_vendor_id` → `vendors`

### `goods_categories`
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `hazard_class` varchar, `tags` json NOT NULL, `incompatible_tags` json NOT NULL, `ptl_allowed` boolean NOT NULL, `requires_special_approval` boolean NOT NULL, `handling_notes` text, `id` char NOT NULL  

### `locations`
Columns: `city` varchar NOT NULL, `district` varchar, `state` varchar NOT NULL, `state_code` varchar, `pincode` varchar, `lat` double, `lng` double, `industrial_area` varchar, `service_verified` boolean NOT NULL, `service_notes` text, `id` char NOT NULL  

### `party_bank_accounts` — Bank details of owners/vendors/drivers/employees. A change creates a new pending row that must be approved (maker-checker) before payments can use it. Old rows are kept.
Columns: `party_type` varchar NOT NULL, `party_id` char NOT NULL, `account_name` varchar NOT NULL, `account_number` varchar NOT NULL, `ifsc` varchar NOT NULL, `bank_name` varchar, `status` varchar NOT NULL, `verified_method` varchar, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  

### `reason_codes`
Columns: `category` varchar NOT NULL, `code` varchar NOT NULL, `label` varchar NOT NULL, `label_ta` varchar, `id` char NOT NULL  

### `route_distances` — Known lane distances (manual or from maps adapter, source recorded).
Columns: `origin_id` char NOT NULL, `destination_id` char NOT NULL, `km` numeric NOT NULL, `toll_estimate` numeric, `source` varchar NOT NULL, `restrictions` text, `id` char NOT NULL  
References: `origin_id` → `locations`, `destination_id` → `locations`

### `vehicle_owners`
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `phone` varchar, `email` varchar, `pan` varchar, `gstin` varchar, `address` text, `kyc_status` varchar NOT NULL, `status` varchar NOT NULL, `routes` json, `tds_section` varchar, `tds_declaration_received` boolean NOT NULL, `rating` numeric, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  

### `vehicle_types`
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `body_type` varchar NOT NULL, `nominal_tons` numeric NOT NULL, `length_ft` numeric, `id` char NOT NULL  

### `vendors`
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `categories` json NOT NULL, `phone` varchar, `email` varchar, `gstin` varchar, `pan` varchar, `address` text, `service_areas` json NOT NULL, `rate_card` json, `approval_status` varchar NOT NULL, `score` json, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  

## Module: commercial

### `booking_versions` — Snapshot of a booking before each authorised modification.
Columns: `booking_id` char NOT NULL, `version` integer NOT NULL, `snapshot` json NOT NULL, `reason` text NOT NULL, `changed_by` char, `changed_at` datetime NOT NULL, `id` char NOT NULL  
References: `booking_id` → `bookings`, `changed_by` → `users`

### `bookings` — A customer consignment. FTL bookings get an exclusive trip; PTL bookings may share a trip.
Columns: `code` varchar NOT NULL, `version` integer NOT NULL, `customer_id` char NOT NULL, `branch_id` char, `quotation_id` char, `service_type` varchar NOT NULL, `service_level` varchar NOT NULL, `ptl_consent` boolean NOT NULL, `consignor_name` varchar NOT NULL, `consignor_address` text, `consignor_gstin` varchar, `consignee_name` varchar NOT NULL, `consignee_address` text, `consignee_phone` varchar, `consignee_gstin` varchar, `origin_id` char NOT NULL, `destination_id` char NOT NULL, `pickup_from` datetime, `pickup_to` datetime, `deliver_by` datetime, `goods_category_id` char, `goods_description` text NOT NULL, `package_count` integer NOT NULL, `weight_kg` numeric NOT NULL, `volume_cft` numeric, `floor_sqft` numeric, `max_package_length_ft` numeric, `stackable` boolean NOT NULL, `fragile` boolean NOT NULL, `declared_value` numeric, `handling` json NOT NULL, `required_body_type` varchar, `instructions` text, `loading_by` varchar NOT NULL, `unloading_by` varchar NOT NULL, `freight_amount` numeric NOT NULL, `extra_charges` json NOT NULL, `gst_mode` varchar NOT NULL, `payment_terms` varchar, `advance_required` numeric NOT NULL, `advance_received` numeric NOT NULL, `credit_status` varchar NOT NULL, `credit_snapshot` json, `status` varchar NOT NULL, `cancellation_terms` text, `cancel_reason` varchar, `created_via` varchar NOT NULL, `delivered_at` datetime, `pod_verified_at` datetime, `delivery_status` varchar, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `customer_id` → `customers`, `branch_id` → `customer_branches`, `quotation_id` → `quotations`, `origin_id` → `locations`, `destination_id` → `locations`, `goods_category_id` → `goods_categories`

### `enquiries`
Columns: `code` varchar NOT NULL, `source` varchar NOT NULL, `campaign` varchar, `customer_id` char, `prospect_name` varchar, `contact_name` varchar, `contact_phone` varchar, `contact_email` varchar, `service_type` varchar NOT NULL, `service_level` varchar NOT NULL, `origin_id` char, `destination_id` char, `origin_text` varchar, `destination_text` varchar, `pickup_from` datetime, `pickup_to` datetime, `deliver_by` datetime, `goods_category_id` char, `goods_description` text, `package_count` integer, `weight_kg` numeric, `volume_cft` numeric, `dimensions` json, `declared_value` numeric, `handling` json NOT NULL, `vehicle_requirement` varchar, `required_documents` json NOT NULL, `owner_user_id` char, `next_action` varchar, `next_action_at` datetime, `status` varchar NOT NULL, `lead_class` varchar, `missing_fields` json NOT NULL, `duplicate_of` char, `lost_reason` varchar, `raw_text` text, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `customer_id` → `customers`, `origin_id` → `locations`, `destination_id` → `locations`, `goods_category_id` → `goods_categories`, `owner_user_id` → `users`, `duplicate_of` → `enquiries`

### `modification_requests` — Customer-requested change: a request until authorised and feasible.
Columns: `booking_id` char NOT NULL, `requested_by` char NOT NULL, `kind` varchar NOT NULL, `changes` json NOT NULL, `reason` text NOT NULL, `status` varchar NOT NULL, `decided_by` char, `decision_note` text, `charges` numeric NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `booking_id` → `bookings`, `requested_by` → `users`, `decided_by` → `users`

### `packages` — Package-level identity for PTL (QR label) and custody scans.
Columns: `booking_id` char NOT NULL, `label` varchar NOT NULL, `seq` integer NOT NULL, `description` varchar, `weight_kg` numeric, `length_ft` numeric, `width_ft` numeric, `height_ft` numeric, `stackable` boolean NOT NULL, `fragile` boolean NOT NULL, `status` varchar NOT NULL, `last_location` varchar, `godown_location` varchar, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `booking_id` → `bookings`

### `quotations` — Each version is its own row. INTERNAL fields (cost, owner quote, margin) are never sent to customers.
Columns: `number` varchar NOT NULL, `version` integer NOT NULL, `enquiry_id` char NOT NULL, `customer_id` char, `service_type` varchar NOT NULL, `service_level` varchar NOT NULL, `vehicle_option` varchar NOT NULL, `vehicle_type_id` char, `distance_km` numeric, `cost_breakdown` json NOT NULL, `internal_cost` numeric NOT NULL, `market_rate` numeric, `owner_quote` numeric, `negotiated_owner_rate` numeric, `direct_expenses` numeric NOT NULL, `floor_price` numeric NOT NULL, `list_price` numeric NOT NULL, `expected_contribution` numeric NOT NULL, `margin_pct` numeric NOT NULL, `ptl_allocation` json, `selling_price` numeric NOT NULL, `discount_pct` numeric NOT NULL, `extra_charges` json NOT NULL, `gst_mode` varchar NOT NULL, `valid_until` datetime NOT NULL, `delivery_window` varchar, `payment_terms` varchar, `assumptions` text, `exclusions` text, `customer_responsibilities` text, `ptl_disclosure` text, `status` varchar NOT NULL, `below_floor` boolean NOT NULL, `approval_id` char, `prepared_by` char, `accepted_at` datetime, `accepted_by` varchar, `acceptance_channel` varchar, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `enquiry_id` → `enquiries`, `customer_id` → `customers`, `vehicle_type_id` → `vehicle_types`, `approval_id` → `approval_requests`, `prepared_by` → `users`

## Module: operations

### `custody_events` — Chain of custody from pickup inspection to POD. Each transfer names who handed over and who received.
Columns: `booking_id` char NOT NULL, `trip_id` char, `event` varchar NOT NULL, `package_count` integer, `expected_count` integer, `condition` varchar, `seal_number` varchar, `from_party` varchar, `to_party` varchar, `handler_vendor_id` char, `facility_id` char, `photo_document_ids` json NOT NULL, `lat` double, `lng` double, `occurred_at` datetime NOT NULL, `recorded_at` datetime NOT NULL, `by_user` char, `note` text, `exception_task_id` char, `id` char NOT NULL  
References: `booking_id` → `bookings`, `trip_id` → `trips`, `handler_vendor_id` → `vendors`, `facility_id` → `facilities`, `by_user` → `users`, `exception_task_id` → `tasks`

### `eway_bills`
Columns: `booking_id` char NOT NULL, `number` varchar, `applicable` boolean NOT NULL, `applicability_reason` text NOT NULL, `valid_from` datetime, `valid_until` datetime, `vehicle_registration` varchar, `source` varchar NOT NULL, `status` varchar NOT NULL, `document_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `booking_id` → `bookings`, `document_id` → `documents`

### `gps_pings`
Columns: `id` bigint NOT NULL, `trip_id` char, `vehicle_id` char NOT NULL, `source` varchar NOT NULL, `lat` double NOT NULL, `lng` double NOT NULL, `speed_kmph` double, `accuracy_m` double, `recorded_at` datetime NOT NULL, `received_at` datetime NOT NULL  
References: `trip_id` → `trips`, `vehicle_id` → `vehicles`

### `lorry_receipts`
Columns: `number` varchar NOT NULL, `booking_id` char NOT NULL, `trip_id` char, `version` integer NOT NULL, `status` varchar NOT NULL, `content` json NOT NULL, `verify_token` varchar NOT NULL, `cancel_reason` text, `amendments` json NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `booking_id` → `bookings`, `trip_id` → `trips`

### `owner_offers` — Attached vehicle: request to an owner → owner quote → negotiation → owner acceptance with actual vehicle/driver.
Columns: `code` varchar NOT NULL, `owner_id` char NOT NULL, `booking_id` char, `trip_id` char, `lane` varchar NOT NULL, `vehicle_requirement` varchar, `required_on` datetime, `owner_quote` numeric, `negotiated_rate` numeric, `advance_pct` numeric NOT NULL, `vehicle_id` char, `driver_id` char, `status` varchar NOT NULL, `accepted_at` datetime, `terms` text, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `owner_id` → `vehicle_owners`, `booking_id` → `bookings`, `trip_id` → `trips`, `vehicle_id` → `vehicles`, `driver_id` → `drivers`

### `package_scans`
Columns: `package_id` char NOT NULL, `trip_id` char, `stage` varchar NOT NULL, `result` varchar NOT NULL, `occurred_at` datetime NOT NULL, `by_user` char, `client_event_id` varchar, `id` char NOT NULL  
References: `package_id` → `packages`, `trip_id` → `trips`, `by_user` → `users`

### `pods`
Columns: `booking_id` char NOT NULL, `trip_id` char NOT NULL, `delivered_count` integer NOT NULL, `expected_count` integer NOT NULL, `receiver_name` varchar NOT NULL, `receiver_phone` varchar, `otp_verified` boolean NOT NULL, `signature_document_id` char, `photo_document_ids` json NOT NULL, `condition` varchar NOT NULL, `remarks` text, `delivered_at` datetime NOT NULL, `lat` double, `lng` double, `status` varchar NOT NULL, `verified_by` char, `verified_at` datetime, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `booking_id` → `bookings`, `trip_id` → `trips`, `signature_document_id` → `documents`, `verified_by` → `users`

### `trip_events`
Columns: `trip_id` char NOT NULL, `booking_id` char, `event` varchar NOT NULL, `occurred_at` datetime NOT NULL, `recorded_at` datetime NOT NULL, `source` varchar NOT NULL, `lat` double, `lng` double, `note` text, `data` json, `by_user` char, `customer_visible` boolean NOT NULL, `id` char NOT NULL  
References: `trip_id` → `trips`, `booking_id` → `bookings`, `by_user` → `users`

### `trip_loads` — A booking (consignment) carried on a trip. PTL trips have several; FTL exactly one.
Columns: `trip_id` char NOT NULL, `booking_id` char NOT NULL, `pickup_seq` integer NOT NULL, `drop_seq` integer NOT NULL, `status` varchar NOT NULL, `loaded_count` integer NOT NULL, `delivered_count` integer NOT NULL, `allocated_cost_est` numeric, `allocated_cost_actual` numeric, `allocation_basis` json, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `trip_id` → `trips`, `booking_id` → `bookings`

### `trips`
Columns: `code` varchar NOT NULL, `trip_mode` varchar NOT NULL, `fleet_type` varchar NOT NULL, `vehicle_id` char NOT NULL, `driver_id` char, `owner_id` char, `exclusive_booking_id` char, `status` varchar NOT NULL, `planned_start` datetime, `actual_start` datetime, `actual_end` datetime, `eta` datetime, `eta_source` varchar, `planned_km` numeric, `start_odometer` integer, `end_odometer` integer, `loaded_km` numeric, `empty_km` numeric, `owner_hire_amount` numeric NOT NULL, `owner_advance` numeric NOT NULL, `load_plan` json, `allocation_checks` json, `override` json, `dispatch_authorized_by` char, `dispatch_authorized_at` datetime, `driver_ack_at` datetime, `gps_consent_at` datetime, `last_lat` double, `last_lng` double, `last_ping_at` datetime, `last_ping_source` varchar, `delay_minutes` integer NOT NULL, `closed_by` char, `closed_at` datetime, `cancel_reason` text, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `vehicle_id` → `vehicles`, `driver_id` → `drivers`, `owner_id` → `vehicle_owners`, `exclusive_booking_id` → `bookings`, `dispatch_authorized_by` → `users`, `closed_by` → `users`

## Module: fleet

### `compliance_items` — Insurance, road tax, permit, FC, PUC, licence etc. with validity for vehicle or driver.
Columns: `subject_type` varchar NOT NULL, `subject_id` char NOT NULL, `kind` varchar NOT NULL, `number` varchar, `valid_from` date, `valid_to` date, `mandatory_for_dispatch` boolean NOT NULL, `document_id` char, `verification` varchar NOT NULL, `status` varchar NOT NULL, `meta` json, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `document_id` → `documents`

### `compliance_renewals` — Renewal workflow: reminder → quote → Owner/Director approval → payment evidence → updated compliance.
Columns: `code` varchar NOT NULL, `compliance_item_id` char NOT NULL, `vendor_id` char, `quote_amount` numeric, `quote_document_id` char, `status` varchar NOT NULL, `approval_id` char, `payment_reference` varchar, `payment_document_id` char, `expense_id` char, `new_item_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `compliance_item_id` → `compliance_items`, `vendor_id` → `vendors`, `quote_document_id` → `documents`, `approval_id` → `approval_requests`, `payment_document_id` → `documents`, `expense_id` → `expenses`, `new_item_id` → `compliance_items`

### `driver_advances`
Columns: `driver_id` char NOT NULL, `trip_id` char, `amount` numeric NOT NULL, `purpose` varchar NOT NULL, `paid_at` datetime, `status` varchar NOT NULL, `adjusted_in_earning_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `driver_id` → `drivers`, `trip_id` → `trips`, `adjusted_in_earning_id` → `driver_earnings`

### `driver_earnings` — Calculated earning per trip (or period). Calculation breakdown is stored for transparency.
Columns: `driver_id` char NOT NULL, `trip_id` char, `period` varchar, `breakdown` json NOT NULL, `gross` numeric NOT NULL, `advances_adjusted` numeric NOT NULL, `adjustments` numeric NOT NULL, `net` numeric NOT NULL, `status` varchar NOT NULL, `settlement_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `driver_id` → `drivers`, `trip_id` → `trips`, `settlement_id` → `settlements`

### `drivers`
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `phone` varchar NOT NULL, `category` varchar NOT NULL, `owner_id` char, `employee_id` char, `licence_number` varchar, `licence_classes` json NOT NULL, `licence_valid_to` date, `hazmat_endorsement` boolean NOT NULL, `experience_years` integer, `languages` json NOT NULL, `emergency_contact` json, `id_number_masked` varchar, `status` varchar NOT NULL, `duty_started_at` datetime, `last_rest_ended_at` datetime, `driving_minutes_today` integer NOT NULL, `training` json NOT NULL, `is_active` boolean NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `owner_id` → `vehicle_owners`, `employee_id` → `employees`

### `fuel_entries`
Columns: `vehicle_id` char NOT NULL, `trip_id` char, `driver_id` char, `filled_at` datetime NOT NULL, `odometer_km` integer NOT NULL, `litres` numeric NOT NULL, `rate` numeric NOT NULL, `amount` numeric NOT NULL, `station` varchar, `bill_number` varchar, `payment_mode` varchar NOT NULL, `full_tank` boolean NOT NULL, `is_adblue` boolean NOT NULL, `receipt_document_id` char, `lat` double, `lng` double, `computed_kmpl` numeric, `anomaly_flags` json NOT NULL, `review_status` varchar NOT NULL, `expense_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `vehicle_id` → `vehicles`, `trip_id` → `trips`, `driver_id` → `drivers`, `receipt_document_id` → `documents`, `expense_id` → `expenses`

### `grievances` — Disputes on attendance, fuel, expenses, damage or remuneration - always human review.
Columns: `code` varchar NOT NULL, `raised_by_user` char NOT NULL, `driver_id` char, `employee_id` char, `topic` varchar NOT NULL, `entity` varchar, `entity_id` varchar, `description` text NOT NULL, `status` varchar NOT NULL, `resolution` text, `resolved_by` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `raised_by_user` → `users`, `driver_id` → `drivers`, `employee_id` → `employees`, `resolved_by` → `users`

### `inspections`
Columns: `vehicle_id` char NOT NULL, `trip_id` char, `driver_id` char, `kind` varchar NOT NULL, `checklist` json NOT NULL, `odometer_km` integer, `fuel_level_pct` integer, `passed` boolean NOT NULL, `notes` text, `occurred_at` datetime NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `vehicle_id` → `vehicles`, `trip_id` → `trips`, `driver_id` → `drivers`

### `job_cards`
Columns: `code` varchar NOT NULL, `vehicle_id` char NOT NULL, `kind` varchar NOT NULL, `description` text NOT NULL, `vendor_id` char, `estimate` numeric NOT NULL, `parts_cost` numeric NOT NULL, `labour_cost` numeric NOT NULL, `status` varchar NOT NULL, `odometer_km` integer, `opened_at` datetime NOT NULL, `completed_at` datetime, `warranty_until` date, `next_due_km` integer, `next_due_date` date, `expense_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `vehicle_id` → `vehicles`, `vendor_id` → `vendors`, `expense_id` → `expenses`

### `remuneration_rules` — One component of a driver's pay. Versioned: changes create a new rule effective prospectively. Only `active` (approved) rules are used in calculations.
Columns: `driver_id` char NOT NULL, `component` varchar NOT NULL, `rate` numeric NOT NULL, `conditions` json, `effective_from` date NOT NULL, `effective_to` date, `status` varchar NOT NULL, `proposed_by` char, `approved_by` char, `version` integer NOT NULL, `reason` text, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `driver_id` → `drivers`, `proposed_by` → `users`, `approved_by` → `users`

### `safety_defects` — A critical open defect blocks dispatch until inspected and released by an authorised person.
Columns: `vehicle_id` char NOT NULL, `item` varchar NOT NULL, `severity` varchar NOT NULL, `description` text, `reported_by` char, `inspection_id` char, `status` varchar NOT NULL, `released_by` char, `release_note` text, `job_card_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `vehicle_id` → `vehicles`, `reported_by` → `users`, `inspection_id` → `inspections`, `released_by` → `users`, `job_card_id` → `job_cards`

### `tyre_events`
Columns: `tyre_id` char NOT NULL, `event` varchar NOT NULL, `vehicle_id` char, `position` varchar, `odometer_km` integer, `tread_mm` numeric, `cost` numeric NOT NULL, `at` datetime NOT NULL, `note` text, `id` char NOT NULL  
References: `tyre_id` → `tyres`, `vehicle_id` → `vehicles`

### `tyres`
Columns: `serial` varchar NOT NULL, `brand` varchar, `size` varchar, `purchase_date` date, `cost` numeric NOT NULL, `vendor_id` char, `vehicle_id` char, `position` varchar, `fitted_odometer` integer, `km_run` integer NOT NULL, `tread_mm` numeric, `retread_count` integer NOT NULL, `status` varchar NOT NULL, `component` varchar NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `vendor_id` → `vendors`, `vehicle_id` → `vehicles`

### `vehicles` — Own or attached vehicle. Capacity checks use legal payload and actual body dimensions, not nominal tons.
Columns: `registration` varchar NOT NULL, `ownership` varchar NOT NULL, `owner_id` char, `vehicle_type_id` char, `make` varchar, `model` varchar, `body_type` varchar NOT NULL, `vehicle_class` varchar, `gvw_kg` integer, `unladen_kg` integer, `payload_kg` integer NOT NULL, `axle_count` integer, `axle_limits_kg` json, `length_ft` numeric NOT NULL, `width_ft` numeric NOT NULL, `height_ft` numeric, `fuel_type` varchar NOT NULL, `tank_litres` numeric, `baseline_kmpl` numeric, `odometer_km` integer NOT NULL, `status` varchar NOT NULL, `home_location_id` char, `current_location_id` char, `available_from` datetime, `finance` json, `can_enter_godown` boolean NOT NULL, `gps_device_id` varchar, `dvr_device_id` varchar, `camera_permission` boolean NOT NULL, `is_active` boolean NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `owner_id` → `vehicle_owners`, `vehicle_type_id` → `vehicle_types`, `home_location_id` → `locations`, `current_location_id` → `locations`

## Module: finance

### `accounts`
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `nature` varchar NOT NULL, `group` varchar NOT NULL, `parent_code` varchar, `is_control` boolean NOT NULL, `is_active` boolean NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  

### `bank_statement_imports`
Columns: `company_bank_id` char NOT NULL, `source` varchar NOT NULL, `filename` varchar, `checksum` varchar NOT NULL, `rows_total` integer NOT NULL, `rows_new` integer NOT NULL, `rows_duplicate` integer NOT NULL, `statement_from` date, `statement_to` date, `closing_balance` numeric, `imported_by` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `company_bank_id` → `company_bank_accounts`, `imported_by` → `users`

### `bank_transactions`
Columns: `company_bank_id` char NOT NULL, `import_id` char, `txn_date` date NOT NULL, `value_date` date, `description` text NOT NULL, `reference` varchar, `debit` numeric NOT NULL, `credit` numeric NOT NULL, `balance` numeric, `mode` varchar, `counterparty` varchar, `dedupe_hash` varchar NOT NULL, `status` varchar NOT NULL, `match_entity` varchar, `match_ids` json, `match_confidence` numeric, `match_reason` text, `matched_by` char, `auto_matched` boolean NOT NULL, `assignee_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `company_bank_id` → `company_bank_accounts`, `import_id` → `bank_statement_imports`, `matched_by` → `users`, `assignee_id` → `users`

### `budgets`
Columns: `period` varchar NOT NULL, `area` varchar NOT NULL, `category` varchar NOT NULL, `amount` numeric NOT NULL, `status` varchar NOT NULL, `approved_by` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `approved_by` → `users`

### `collection_notes`
Columns: `customer_id` char NOT NULL, `invoice_id` char, `kind` varchar NOT NULL, `note` text NOT NULL, `promise_date` date, `promise_amount` numeric, `status` varchar NOT NULL, `by_user` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `customer_id` → `customers`, `invoice_id` → `invoices`, `by_user` → `users`

### `expenses`
Columns: `code` varchar NOT NULL, `category` varchar NOT NULL, `expense_date` date NOT NULL, `amount` numeric NOT NULL, `tax_amount` numeric NOT NULL, `vendor_id` char, `vendor_name` varchar, `bill_number` varchar, `trip_id` char, `vehicle_id` char, `driver_id` char, `booking_id` char, `paid_by` varchar NOT NULL, `payment_mode` varchar, `rebillable` boolean NOT NULL, `receipt_document_id` char, `ocr` json, `duplicate_of` char, `status` varchar NOT NULL, `submitted_by` char, `approved_by` char, `reject_reason` text, `voucher_id` char, `occurred_at` datetime, `source` varchar NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `vendor_id` → `vendors`, `trip_id` → `trips`, `vehicle_id` → `vehicles`, `driver_id` → `drivers`, `booking_id` → `bookings`, `receipt_document_id` → `documents`, `duplicate_of` → `expenses`, `submitted_by` → `users`, `approved_by` → `users`, `voucher_id` → `vouchers`

### `import_batches` — Data migration batch (Excel / Tally XML / CSV): dry run → preview → approval → commit → reversal.
Columns: `code` varchar NOT NULL, `kind` varchar NOT NULL, `filename` varchar NOT NULL, `checksum` varchar NOT NULL, `status` varchar NOT NULL, `preview` json NOT NULL, `exceptions` json NOT NULL, `created_by` char, `approved_by` char, `committed_ids` json NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `created_by` → `users`, `approved_by` → `users`

### `invoice_lines`
Columns: `invoice_id` char NOT NULL, `booking_id` char, `lr_number` varchar, `charge_code` varchar NOT NULL, `description` varchar NOT NULL, `amount` numeric NOT NULL, `is_pass_through` boolean NOT NULL, `active` boolean NOT NULL, `id` char NOT NULL  
References: `invoice_id` → `invoices`, `booking_id` → `bookings`

### `invoices`
Columns: `number` varchar NOT NULL, `customer_id` char NOT NULL, `invoice_date` date NOT NULL, `due_date` date NOT NULL, `gst_mode` varchar NOT NULL, `place_of_supply` varchar, `taxable_value` numeric NOT NULL, `cgst` numeric NOT NULL, `sgst` numeric NOT NULL, `igst` numeric NOT NULL, `pass_through` numeric NOT NULL, `total` numeric NOT NULL, `amount_received` numeric NOT NULL, `tds_received` numeric NOT NULL, `status` varchar NOT NULL, `tax_rule_snapshot` json NOT NULL, `irn` varchar, `irn_status` varchar NOT NULL, `voucher_id` char, `cancel_reason` text, `created_by` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `customer_id` → `customers`, `voucher_id` → `vouchers`, `created_by` → `users`

### `payments` — Outgoing payment. Prepared by one user, approved by another; executed only after approval. The system never pays autonomously.
Columns: `code` varchar NOT NULL, `payee_type` varchar NOT NULL, `payee_id` char, `payee_name` varchar NOT NULL, `bank_account_id` char, `company_bank_id` char, `amount` numeric NOT NULL, `purpose` varchar NOT NULL, `settlement_id` char, `expense_id` char, `vendor_invoice_id` char, `mode` varchar NOT NULL, `status` varchar NOT NULL, `prepared_by` char NOT NULL, `approved_by` char, `executed_by` char, `executed_via` varchar, `bank_reference` varchar, `executed_at` datetime, `idempotency_key` varchar NOT NULL, `voucher_id` char, `bank_txn_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `bank_account_id` → `party_bank_accounts`, `company_bank_id` → `company_bank_accounts`, `settlement_id` → `settlements`, `expense_id` → `expenses`, `vendor_invoice_id` → `vendor_invoices`, `prepared_by` → `users`, `approved_by` → `users`, `executed_by` → `users`, `voucher_id` → `vouchers`, `bank_txn_id` → `bank_transactions`

### `receipt_allocations`
Columns: `receipt_id` char NOT NULL, `invoice_id` char NOT NULL, `amount` numeric NOT NULL, `tds_amount` numeric NOT NULL, `id` char NOT NULL  
References: `receipt_id` → `receipts`, `invoice_id` → `invoices`

### `receipts`
Columns: `number` varchar NOT NULL, `customer_id` char, `receipt_date` date NOT NULL, `amount` numeric NOT NULL, `tds_amount` numeric NOT NULL, `mode` varchar NOT NULL, `reference` varchar, `company_bank_id` char, `bank_txn_id` char, `status` varchar NOT NULL, `is_advance` boolean NOT NULL, `booking_id` char, `unallocated` numeric NOT NULL, `voucher_id` char, `remittance_note` text, `planned_allocations` json, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `customer_id` → `customers`, `company_bank_id` → `company_bank_accounts`, `bank_txn_id` → `bank_transactions`, `booking_id` → `bookings`, `voucher_id` → `vouchers`

### `settlements`
Columns: `code` varchar NOT NULL, `party_type` varchar NOT NULL, `party_id` char NOT NULL, `period_from` date, `period_to` date, `lines` json NOT NULL, `gross` numeric NOT NULL, `advances` numeric NOT NULL, `adjustments` numeric NOT NULL, `tds` numeric NOT NULL, `net_payable` numeric NOT NULL, `paid` numeric NOT NULL, `status` varchar NOT NULL, `prepared_by` char, `approved_by` char, `voucher_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `prepared_by` → `users`, `approved_by` → `users`, `voucher_id` → `vouchers`

### `voucher_lines`
Columns: `voucher_id` char NOT NULL, `account_id` char NOT NULL, `debit` numeric NOT NULL, `credit` numeric NOT NULL, `party_type` varchar, `party_id` char, `cost_centre` varchar, `booking_id` char, `trip_id` char, `vehicle_id` char, `line_narration` varchar, `id` char NOT NULL  
References: `voucher_id` → `vouchers`, `account_id` → `accounts`, `booking_id` → `bookings`, `trip_id` → `trips`, `vehicle_id` → `vehicles`

### `vouchers` — Posted vouchers are never edited or deleted - corrections are made by reversal.
Columns: `number` varchar NOT NULL, `vtype` varchar NOT NULL, `vdate` date NOT NULL, `fy` varchar NOT NULL, `narration` text NOT NULL, `status` varchar NOT NULL, `source_entity` varchar, `source_id` varchar, `reversal_of` char, `reversed_by` char, `created_by` char, `approved_by` char, `total` numeric NOT NULL, `external_ref` varchar, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `reversal_of` → `vouchers`, `reversed_by` → `vouchers`, `created_by` → `users`, `approved_by` → `users`

## Module: supply

### `godown_entries` — Consignment held at a verified facility (inward GRN → location → outward).
Columns: `code` varchar NOT NULL, `facility_id` char NOT NULL, `booking_id` char NOT NULL, `package_count` integer NOT NULL, `condition` varchar NOT NULL, `location` varchar, `inward_at` datetime NOT NULL, `outward_at` datetime, `outward_trip_id` char, `outward_count` integer, `storage_rate_per_day` numeric NOT NULL, `handling_cost` numeric NOT NULL, `photo_document_ids` json NOT NULL, `status` varchar NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `facility_id` → `facilities`, `booking_id` → `bookings`, `outward_trip_id` → `trips`

### `goods_receipts` — Receipt of goods or proof of service completion against a PO.
Columns: `code` varchar NOT NULL, `po_id` char NOT NULL, `lines` json NOT NULL, `accepted_amount` numeric NOT NULL, `evidence_document_ids` json NOT NULL, `inspected_by` char, `received_at` datetime NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `po_id` → `purchase_orders`, `inspected_by` → `users`

### `inventory_items`
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `category` varchar NOT NULL, `uom` varchar NOT NULL, `facility_id` char, `min_qty` numeric NOT NULL, `max_qty` numeric NOT NULL, `qty_on_hand` numeric NOT NULL, `avg_cost` numeric NOT NULL, `serial_tracked` boolean NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `facility_id` → `facilities`

### `purchase_orders`
Columns: `code` varchar NOT NULL, `request_id` char, `vendor_id` char NOT NULL, `kind` varchar NOT NULL, `lines` json NOT NULL, `amount` numeric NOT NULL, `tax_amount` numeric NOT NULL, `status` varchar NOT NULL, `vendor_status_note` text, `issued_by` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `request_id` → `purchase_requests`, `vendor_id` → `vendors`, `issued_by` → `users`

### `purchase_requests`
Columns: `code` varchar NOT NULL, `category` varchar NOT NULL, `description` text NOT NULL, `items` json NOT NULL, `estimated_amount` numeric NOT NULL, `vehicle_id` char, `job_card_id` char, `trip_id` char, `emergency` boolean NOT NULL, `emergency_reason` text, `status` varchar NOT NULL, `requested_by` char NOT NULL, `shortlist` json NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `vehicle_id` → `vehicles`, `job_card_id` → `job_cards`, `trip_id` → `trips`, `requested_by` → `users`

### `rfq_quotes`
Columns: `request_id` char NOT NULL, `vendor_id` char NOT NULL, `amount` numeric NOT NULL, `tax_amount` numeric NOT NULL, `delivery_days` integer, `notes` text, `submitted_via` varchar NOT NULL, `selected` boolean NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `request_id` → `purchase_requests`, `vendor_id` → `vendors`

### `stock_movements`
Columns: `item_id` char NOT NULL, `kind` varchar NOT NULL, `qty` numeric NOT NULL, `unit_cost` numeric NOT NULL, `vehicle_id` char, `job_card_id` char, `trip_id` char, `grn_id` char, `serial` varchar, `reason` text, `at` datetime NOT NULL, `by_user` char, `id` char NOT NULL  
References: `item_id` → `inventory_items`, `vehicle_id` → `vehicles`, `job_card_id` → `job_cards`, `trip_id` → `trips`, `grn_id` → `goods_receipts`, `by_user` → `users`

### `vendor_invoices`
Columns: `code` varchar NOT NULL, `vendor_id` char NOT NULL, `po_id` char, `invoice_number` varchar NOT NULL, `invoice_date` date NOT NULL, `amount` numeric NOT NULL, `tax_amount` numeric NOT NULL, `tds_amount` numeric NOT NULL, `match_result` json, `status` varchar NOT NULL, `document_id` char, `submitted_via` varchar NOT NULL, `voucher_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `vendor_id` → `vendors`, `po_id` → `purchase_orders`, `document_id` → `documents`, `voucher_id` → `vouchers`

## Module: risk

### `claims` — Financially separates gross loss, insurance receivable, deductible, compensation, recoveries and cash received.
Columns: `code` varchar NOT NULL, `incident_id` char NOT NULL, `policy_id` char, `direction` varchar NOT NULL, `insurer_claim_number` varchar, `surveyor` varchar, `notified_at` datetime, `notify_deadline` datetime, `gross_loss` numeric NOT NULL, `claimed_amount` numeric NOT NULL, `deductible` numeric NOT NULL, `assessed_amount` numeric, `customer_compensation` numeric NOT NULL, `recoveries` numeric NOT NULL, `salvage` numeric NOT NULL, `cash_received` numeric NOT NULL, `status` varchar NOT NULL, `timeline` json NOT NULL, `financial_treatment_approval_id` char, `voucher_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `incident_id` → `incidents`, `policy_id` → `insurance_policies`, `financial_treatment_approval_id` → `approval_requests`, `voucher_id` → `vouchers`

### `complaints`
Columns: `code` varchar NOT NULL, `customer_id` char, `booking_id` char, `trip_id` char, `category` varchar NOT NULL, `description` text NOT NULL, `priority` varchar NOT NULL, `channel` varchar NOT NULL, `owner_user_id` char, `response_due_at` datetime, `resolve_due_at` datetime, `status` varchar NOT NULL, `root_cause` text, `corrective_action` text, `resolution` text, `escalated` boolean NOT NULL, `incident_id` char, `communications` json NOT NULL, `raised_by` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `customer_id` → `customers`, `booking_id` → `bookings`, `trip_id` → `trips`, `owner_user_id` → `users`, `incident_id` → `incidents`, `raised_by` → `users`

### `incidents`
Columns: `code` varchar NOT NULL, `kind` varchar NOT NULL, `severity` varchar NOT NULL, `occurred_at` datetime NOT NULL, `location_text` varchar, `lat` double, `lng` double, `vehicle_id` char, `driver_id` char, `trip_id` char, `booking_id` char, `description` text NOT NULL, `people` json NOT NULL, `witnesses` json NOT NULL, `emergency_actions` text, `authority_reference` varchar, `evidence_document_ids` json NOT NULL, `legal_hold` boolean NOT NULL, `status` varchar NOT NULL, `reported_by` char, `source` varchar NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `vehicle_id` → `vehicles`, `driver_id` → `drivers`, `trip_id` → `trips`, `booking_id` → `bookings`, `reported_by` → `users`

### `insurance_policies`
Columns: `kind` varchar NOT NULL, `insurer` varchar NOT NULL, `policy_number` varchar NOT NULL, `insured_parties` text, `vehicle_id` char, `coverage` text, `sum_insured` numeric, `premium` numeric, `deductible` numeric, `exclusions` text, `conditions` text, `limits` json, `endorsements` json NOT NULL, `valid_from` date NOT NULL, `valid_to` date NOT NULL, `claim_contact` varchar, `notification_deadline_hours` integer, `wording_verified` boolean NOT NULL, `document_id` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `vehicle_id` → `vehicles`, `document_id` → `documents`

### `legal_cases`
Columns: `code` varchar NOT NULL, `kind` varchar NOT NULL, `title` varchar NOT NULL, `parties` json NOT NULL, `forum` varchar, `advocate` varchar, `served_on` date, `response_due` date, `next_hearing` date, `exposure` numeric, `next_action` text, `status` varchar NOT NULL, `legal_hold` boolean NOT NULL, `incident_id` char, `evidence_document_ids` json NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `incident_id` → `incidents`

## Module: people

### `ai_recommendations` — Something an assistant proposes. Execution needs an authorised human (and never the AI itself).
Columns: `assistant` varchar NOT NULL, `kind` varchar NOT NULL, `title` varchar NOT NULL, `reasoning` text NOT NULL, `confidence` numeric NOT NULL, `data_freshness` varchar, `entity` varchar, `entity_id` varchar, `proposed_action` json, `status` varchar NOT NULL, `for_user` char, `decided_by` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `for_user` → `users`, `decided_by` → `users`

### `ai_usage`
Columns: `at` datetime NOT NULL, `provider` varchar NOT NULL, `model` varchar NOT NULL, `assistant` varchar NOT NULL, `user_id` char, `app` varchar NOT NULL, `input_tokens` integer NOT NULL, `output_tokens` integer NOT NULL, `cost_inr` numeric NOT NULL, `status` varchar NOT NULL, `prompt_version` varchar, `tools_used` json NOT NULL, `id` char NOT NULL  
References: `user_id` → `users`

### `attendance`
Columns: `employee_id` char NOT NULL, `day` date NOT NULL, `status` varchar NOT NULL, `in_at` datetime, `out_at` datetime, `overtime_hours` numeric NOT NULL, `source` varchar NOT NULL, `corrected_by` char, `correction_reason` text, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `employee_id` → `employees`, `corrected_by` → `users`

### `campaigns`
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `channels` json NOT NULL, `audience` text, `budget` numeric NOT NULL, `spent` numeric NOT NULL, `starts_on` date, `ends_on` date, `status` varchar NOT NULL, `approved_by` char, `leads` integer NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `approved_by` → `users`

### `checklist_runs`
Columns: `template_id` char NOT NULL, `period_key` varchar NOT NULL, `results` json NOT NULL, `completed_by` char, `completed_at` datetime, `status` varchar NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `template_id` → `checklist_templates`, `completed_by` → `users`

### `checklist_templates`
Columns: `code` varchar NOT NULL, `title` varchar NOT NULL, `frequency` varchar NOT NULL, `department` varchar NOT NULL, `owner_role` varchar NOT NULL, `backup_role` varchar, `items` json NOT NULL, `due_hour` integer NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  

### `content_items`
Columns: `campaign_id` char, `channel` varchar NOT NULL, `kind` varchar NOT NULL, `title` varchar NOT NULL, `body` text NOT NULL, `language` varchar NOT NULL, `media_document_ids` json NOT NULL, `media_consent_confirmed` boolean NOT NULL, `drafted_by_agent` varchar, `status` varchar NOT NULL, `scheduled_for` datetime, `published_at` datetime, `publish_mode` varchar, `approved_by` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `campaign_id` → `campaigns`, `approved_by` → `users`

### `employees`
Columns: `code` varchar NOT NULL, `name` varchar NOT NULL, `department` varchar NOT NULL, `designation` varchar, `employment_type` varchar NOT NULL, `phone` varchar, `email` varchar, `joined_on` date, `exited_on` date, `emergency_contact` json, `monthly_salary` numeric NOT NULL, `salary_components` json, `statutory` json, `is_driver` boolean NOT NULL, `backup_employee_id` char, `status` varchar NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `backup_employee_id` → `employees`

### `leave_requests`
Columns: `employee_id` char, `driver_id` char, `from_date` date NOT NULL, `to_date` date NOT NULL, `kind` varchar NOT NULL, `reason` text, `status` varchar NOT NULL, `decided_by` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `employee_id` → `employees`, `driver_id` → `drivers`, `decided_by` → `users`

### `opportunities` — Business opportunity database. Presence here does NOT imply G ROAD LINES serves that location.
Columns: `name` varchar NOT NULL, `industry` varchar, `city` varchar, `state` varchar, `lat` double, `lng` double, `source` varchar NOT NULL, `source_date` date, `confidence` varchar NOT NULL, `data_kind` varchar NOT NULL, `stage` varchar NOT NULL, `estimated_monthly_value` numeric, `owner_user_id` char, `customer_id` char, `next_follow_up` date, `priority` integer NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `owner_user_id` → `users`, `customer_id` → `customers`

### `payroll_runs`
Columns: `period` varchar NOT NULL, `status` varchar NOT NULL, `totals` json NOT NULL, `rules_snapshot` json NOT NULL, `prepared_by` char, `approved_by` char, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `prepared_by` → `users`, `approved_by` → `users`

### `payslips`
Columns: `run_id` char NOT NULL, `employee_id` char NOT NULL, `days_payable` numeric NOT NULL, `earnings` json NOT NULL, `deductions` json NOT NULL, `gross` numeric NOT NULL, `net` numeric NOT NULL, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `run_id` → `payroll_runs`, `employee_id` → `employees`

### `sop_acks`
Columns: `sop_id` char NOT NULL, `user_id` char NOT NULL, `at` datetime NOT NULL, `id` char NOT NULL  
References: `sop_id` → `sops`, `user_id` → `users`

### `sops`
Columns: `code` varchar NOT NULL, `version` integer NOT NULL, `title` varchar NOT NULL, `department` varchar NOT NULL, `purpose` text, `scope` text, `owner_role` varchar, `approver_role` varchar, `steps` json NOT NULL, `required_documents` json NOT NULL, `escalation` text, `effective_from` date, `status` varchar NOT NULL, `approved_by` char, `change_note` text, `id` char NOT NULL, `created_at` datetime NOT NULL, `updated_at` datetime NOT NULL  
References: `approved_by` → `users`

