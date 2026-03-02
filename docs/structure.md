# Structure of the Application

This document breaks down how the code is organized, what each directory does, and *why* it was designed this way.

## 📂 Directory Breakdown

### `agent/`
**What it is:** The FastAPI Python web service that hosts our AI agents.
**Why it's here:** Databricks is great for heavy lifting and data crunching, but we want a lightweight, highly responsive, and independently scalable API to handle the actual decision-making. 
*   `app/main.py`: The entry point. It receives HTTP requests and routes them through the agents.
*   `app/agents/`: Contains the four specialist agents (`triage`, `risk_scoring`, `compliance`, `investigation`). Separating them makes the code easier to test and maintain.
*   `app/mcp_server.py`: The "Tools" registry. It gives the agents strict, well-defined abilities (like `get_transaction_features` or `write_audit_event`).
*   `app/schemas.py`: Built using Pydantic. This ensures that data passed between agents is strictly formatted. If a transaction is missing an ID, the application fails safely rather than crashing the AI.

### `databricks/`
**What it is:** The data pipeline and analytics engine.
**Why it's here:** We need to process hundreds of thousands of transactions, clean them, and evaluate them. Databricks (built on Apache Spark) is designed exactly for this massive scale.
*   `notebooks/01` to `04`: The Medallion Pipeline. Data flows from raw CSVs to highly refined Gold Delta tables.
*   `notebooks/05_eval_baseline.py`: A traditional Machine Learning model (Logistic Regression) used as a baseline to compare our AI agents against.
*   `notebooks/07_batch_verification.py`: The ultimate test. It grabs thousands of transactions from the Gold tables and fires them at our `agent/` API to see how the agents perform at scale.
*   `jobs/fraud_pipeline.yml`: The automation script. Instead of clicking "Run" on notebooks manually, this file defines how Databricks should run them automatically in sequence.

### `synthetic/`
**What it is:** Python scripts that generate fake, but highly realistic, transaction data.
**Why it's here:** To test a fraud system, you need fraud. Traditional generated data is just random numbers. Our generator (`scenarios.py`) creates specific *stories* (like a teenager testing stolen cards with $1.00 charges) so we can see if our AI catches the specific story.

### `infra/terraform/`
**What it is:** "Infrastructure as Code". Files that define the cloud servers, storage, and security.
**Why it's here:** Clicking around the Azure portal to create servers is error-prone. Terraform allows us to write code that says "Create a Storage Account, a Web App, and a Key Vault, and link them securely." We can run it, tear it down, and run it again perfectly every time.
*   `main.tf`: The core blueprints for all Azure resources.
*   `variables.tf` / `outputs.tf`: Inputs (like region) and outputs (like the URL of the created Web App).

### `.github/workflows/`
**What it is:** CI/CD (Continuous Integration / Continuous Deployment) pipelines.
**Why it's here:** When developers push new code, we want it deployed automatically and safely.
*   `terraform.yml`: Checks the infrastructure code and automatically applies changes to Azure.
*   `deploy-agent.yml`: Packages the `agent/` code into a Docker container, uploads it to GitHub, and tells the Azure Web App to restart using the new code.

---

## 🏛️ Architectural Principles (The "Why")

1.  **Separation of Concerns:** The data engineers work in `databricks/`. The backend AI engineers work in `agent/`. The DevOps team works in `infra/`. Nobody steps on anyone's toes.
2.  **Least Privilege Security:** The Agent application has an "Identity" in Azure. It is *only* allowed to read secrets from Key Vault and write logs to the Storage Account. It cannot delete the database or change underlying infrastructure.
3.  **Cost Guardrails:** Databricks clusters cost money when running. Our `fraud_pipeline.yml` uses "Job Clusters" that spin up, do the work, and instantly shut down (with a 10-minute auto-terminate). 
4.  **Traceability:** Every action by an agent creates an `AgentEventLog` tagged with a unique `trace_id`. If the AI blocks a transaction incorrectly, we can trace the exact logs to see *why* and tune the system.
