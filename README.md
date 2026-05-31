# ABA Clinical Data Platform

A synthetic-data clinical platform modeling a small ABA practice — schema, 
seed data, and (eventually) orchestration, transformation, and analytics layers. 
Built as a portfolio project pairing AI pair-programming with an ABA subject-
matter expert and years of data work.

## Project status

Currently: schema and reference seed data are complete. Synthetic transactional 
data generation, dbt transformations, and the analytics layer are next.

## Disclosure

All clients, clinicians, and clinical data in this repository are synthetically 
generated to resemble real ABA documentation without representing any real 
person or practice. No PHI is used or shared.

## Running locally

1. Clone this repository.
2. Copy `.env.example` to `.env` and set your own values.
3. Run `docker-compose up -d`. The database will start with reference data loaded.

## Workflow ER Diagram (Schema v3)

Workflow-oriented entity-relationship diagram for the ABA clinical data platform. Pure lookup tables (`cpt_codes`, `staff_credentials`, `skill_areas`, `intervention_types`, `place_of_service_codes`) and the `audit_log` are omitted to keep the focus on entities that move data through the case lifecycle. Cardinalities follow crow's-foot notation: `||` = exactly one, `o|` = zero or one, `o{` = zero or more.

**New or modified in v3:**
- `document_types` lookup table (new)
- `client_documents` table (new)
- `authorizations.units_requested` (new) — what the BCBA asked the payer for
- `authorizations.units_authorized` (now nullable) — what the payer granted; NULL while pending or denied
- `authorizations.submitted_at` (new) — when the request went out
- `authorizations.decision_at` (new) — when the payer responded
- `treatment_plans.signed_by_guardian_at` (new) — parent signature timestamp, gates payer submission
- `treatment_plans.guardian_name` (new)

```mermaid
erDiagram
    clients {
        int id PK
        string diagnosis_code
        int supervising_bcba_id FK
        date intake_date
    }
    staff {
        int id PK
        string credential
        boolean is_owner
    }
    document_types {
        string name PK
        boolean required_for_intake
        boolean has_expiration
    }
    client_documents {
        int id PK
        int client_id FK
        string document_type FK
        date received_date
        date expiration_date
    }
    service_locations {
        int id PK
        int client_id FK
        string label
    }
    payers {
        int id PK
        string name
        string payer_type
    }
    authorizations {
        int id PK
        int client_id FK
        int payer_id FK
        string cpt_code
        int units_requested
        int units_authorized
        timestamp submitted_at
        timestamp decision_at
        string status
    }
    treatment_plans {
        int id PK
        int client_id FK
        timestamp signed_at
        timestamp signed_by_guardian_at
        string guardian_name
        timestamp submitted_at
    }
    programs {
        int id PK
        int client_id FK
        string skill_area
        string status
    }
    targets {
        int id PK
        int program_id FK
        string measurement_type
        string status
    }
    sessions {
        int id PK
        int client_id FK
        int authorization_id FK
        int rendering_provider_id FK
        string cpt_code
        string status
    }
    session_target_data {
        int id PK
        int session_id FK
        int target_id FK
        string measurement_type
    }
    behavior_incidents {
        int id PK
        int session_id FK
        text antecedent
        string intensity
    }
    session_notes {
        int session_id PK
        text session_narrative
    }
    claims {
        int id PK
        int session_id FK
        int authorization_id FK
        decimal amount_billed
        string status
    }

    staff ||--o{ clients : "supervises (BCBA)"
    staff ||--o{ sessions : renders
    staff o|--o{ client_documents : uploads

    clients ||--o{ client_documents : has
    clients ||--o{ service_locations : has
    clients ||--o{ authorizations : has
    clients ||--o{ treatment_plans : has
    clients ||--o{ programs : "enrolled in"
    clients ||--o{ sessions : receives

    document_types ||--o{ client_documents : types

    payers ||--o{ authorizations : approves
    payers ||--o{ claims : adjudicates

    treatment_plans o|--o{ authorizations : covers
    treatment_plans ||--o{ programs : introduces

    authorizations ||--o{ sessions : "billed against"
    authorizations ||--o{ claims : "billed under"

    programs ||--o{ targets : has
    targets ||--o{ session_target_data : "measured via"

    sessions ||--o{ session_target_data : captures
    sessions ||--o{ behavior_incidents : captures
    sessions ||--o| session_notes : "documented in"
    sessions ||--o{ claims : "billed via"
```
