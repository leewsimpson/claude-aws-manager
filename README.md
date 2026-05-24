# Claude Code AWS Bedrock Manager

A self-service web application for provisioning and managing Claude Code access via AWS Bedrock within an organisation. Automates credential creation, approval workflows, and cost governance — no manual AWS console steps required after initial setup.

## What It Does

- **Developers** request API keys, view usage, and configure Claude Code locally
- **Cost Centre Owners** approve/reject requests, set token budgets and model restrictions per key
- **Administrators** manage projects, users, and global platform settings

Developers use provisioned bearer tokens in their terminal to call AWS Bedrock directly. The platform governs credentials but does not sit in the inference path.

## Tech Stack

| Layer    | Technology               |
|----------|--------------------------|
| Frontend | React, Vite, TypeScript  |
| Backend  | Python, FastAPI          |
| Database | PostgreSQL (SQLAlchemy)  |
| Cloud    | AWS (IAM, Bedrock, CloudWatch, Price List API) |

## Documentation

- [Requirements](docs/requirements.md)
- [Design](docs/design.md)
- [Data Model](docs/data-model.md)
- [Design Decisions](docs/design-decisions.md)
- [Implementation Plan](docs/implementation-plan.md)
- [Tech Spike](docs/tech-spike.md)
