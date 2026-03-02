# Deployment Guide: Azure & Databricks

This guide provides a step-by-step walkthrough of how to deploy the Fraud Detection Platform from your local machine to the Azure cloud. This is written for someone who may be newer to DevOps and cloud infrastructure.

---

## 🛠️ Prerequisites

Before you start, make sure you have the following installed on your computer:
1.  **[Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)**: To log into Azure from the command line.
2.  **[Terraform](https://developer.hashicorp.com/terraform/downloads)**: To build the Microsoft Azure servers.
3.  **[Docker](https://docs.docker.com/get-docker/)**: To package our FastAPI Agent code into a container.
4.  **[Databricks CLI](https://docs.databricks.com/en/dev-tools/cli/index.html)**: To push our data pipeline notebooks directly into the cloud.

You will also need an **Azure Subscription** and a **GitHub account**.

---

## 🌎 Step 1: Provision Cloud Infrastructure (Terraform)

Terraform reads our `infra/terraform/*.tf` files and asks Azure to build everything for us automatically. 

1.  **Log into Azure:**
    ```bash
    az login
    ```
    *(This will open a browser window for you to sign in. Once signed in, close it and return to the terminal).*

2.  **Move into the Terraform directory:**
    ```bash
    cd infra/terraform
    ```

3.  **Initialize Terraform:**
    ```bash
    terraform init
    ```
    *(This downloads the "plugins" Terraform needs to talk to Azure).*

4.  **Review the Plan and Apply:**
    ```bash
    terraform apply
    ```
    *   Terraform will show you exactly what it is about to build (Key Vault, Storage Account, Web App, Databricks Workspace).
    *   It will ask you to provide three variables:
        *   `admin_object_id`: Your Azure User ID (run `az ad signed-in-user show --query id -o tsv` to get this).
        *   `azure_ai_api_key`: The secret API key. If you don't have this yet, entering a dummy string like `dummy-key-123` is completely fine to get the servers built!
        *   `azure_ai_endpoint`: The URL for the AI. If you don't have it, enter `https://dummy.openai.azure.com/`. 
        *(Note: If you want to use the live AI later, you can find the real endpoint and key by searching "Azure OpenAI" in the Azure Portal, clicking your resource, and going to "Keys and Endpoint" on the left menu).*
    *   Type `yes` when prompted. Wait 5-10 minutes while Azure builds the resources.
    *   **CRITICAL**: Note the `outputs` at the very end of the script (e.g. `agent_app_url`, `databricks_workspace_url`). You will need these!

---

## 🐳 Step 2: Build & Deploy the AI Agent

Our AI Agent isn't just a script; it's a web API built with FastAPI. We need to package it into a "Docker Container" so it runs exactly the same way in the cloud as it does on your laptop.

1.  **Move back to the agent directory:**
    ```bash
    cd ../../agent
    ```

2.  **Build the Container:**
    ```bash
    docker build -t fraud-agent .
    ```
    *(This translates the `Dockerfile` into a runnable image).*

3.  **Push the Container to GitHub Container Registry (GHCR):**
    For the cloud to run your image, it needs to be hosted online. We use GitHub's free registry.

    **How to get a GitHub Personal Access Token (PAT):**
    1. Go to [GitHub Settings > Developer Settings > Personal access tokens > Tokens (classic)](https://github.com/settings/tokens).
    2. Click **"Generate new token (classic)"**.
    3. Give it a name, and check the following scopes: `write:packages`, `read:packages`, and `delete:packages` (this automatically checks the `repo` scope as well, which is fine).
    4. Click **Generate token** and copy the string (it starts with `ghp_`). 

    Now use it to log in and push:
    ```bash
    # Log into GHCR inside docker
    echo <your_github_personal_access_token> | docker login ghcr.io -u <your_github_username> --password-stdin
    
    # Tag it
    docker tag fraud-agent ghcr.io/<your_github_username>/fraud-agent:latest
    
    # Push it
    docker push ghcr.io/<your_github_username>/fraud-agent:latest
    ```

4.  **Set up the GitHub Repository & Workflows:**
    For the `.github/workflows` to run automatically in the future, you must push this local project up to a brand new repository on GitHub:
    ```bash
    git init
    git add .
    git commit -m "Initial commit of Fraud Detection Platform"
    git branch -M main
    git remote add origin https://github.com/<your_github_username>/<your-repo-name>.git
    git push -u origin main
    ```
    
    **Tell Azure to Use It:**
    The GitHub Actions deployment pipeline (`.github/workflows/deploy-agent.yml`) will automatically handle pushing new code every time you make a git commit to the main branch. However, for this very first setup, you need to manually tell the Azure Web App to restart to pull the image you just pushed:
    ```bash
    az webapp restart --name app-fraudagentdev3 --resource-group rg-fraudagentdev3
    ```

---

## 🚀 Step 3: Set up Databricks and the Data Pipeline

Now that the servers are up, we need to load our Databricks notebooks into the Databricks Workspace that Terraform created for us.

1.  **Log into Databricks CLI:**
    You'll need a Personal Access Token from your new Databricks Workspace URL (which was in your Terraform outputs).
    ```bash
    databricks configure --token
    # Enter the Workspace URL and Token when prompted
    ```

2.  **Import the Notebooks:**
    This copies all the Python scripts in `databricks/notebooks` directly into the cloud.
    ```bash
    cd ../
    databricks workspace import_dir databricks/notebooks /Shared/fraud-detection/notebooks
    ```

3.  **Upload the Data:**
    Our Pipeline expects raw data to live in the new Azure Storage Account (`raw` container). Use `azcopy` or the Azure Portal to upload the Kaggle Credit Card CSV into that container.

4.  **Configure and Run the Job Pipeline:**
    We wrote an automated sequence script called `fraud_pipeline.yml`. 
    You can import this directly via the Databricks UI (Workflows -> Jobs -> Edit YAML) or use the Databricks CLI "Asset Bundles" feature to deploy it.
    
    When you click "Run Now" in Databricks, the pipeline will:
    *   Ingest the raw Kaggle data (`01`, `02`)
    *   Clean and extract features (`03`, `04`)
    *   Run the baseline prediction (`05`)
    *   Ingest dummy synthetic fraud (`06`)
    *   Finally, send *thousands* of requests to your newly deployed FastAPI Agent to see how it performs (`07`).

---

## 📊 Step 4: Verify and Analyze Logs

Every time the FastAPI Agent makes a decision, it writes a `logs/audit_events.jsonl` file directly into your secure Azure Storage Account.

To see the results:
1.  Open the final `results.agent_decisions` table within a Databricks SQL Warehouse (or notebook).
2.  Run the queries found in `databricks/sql/queries.sql`. 
3.  You will see:
    *   How many transactions the agent blocked.
    *   How accurate it was on the synthetic test scenarios.
    *   The explicit reasoning returned by the Large Language Model.
