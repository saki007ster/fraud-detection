# Features and How It Works

This document explains what the Fraud Detection Platform does, its core features, and how everything works under the hood. It is written to be easily understandable, even if you are new to the platform.

---

## 🚀 Core Features

### 1. Multi-Agent Fraud Analysis
Instead of relying on a single complex model, this application uses a team of AI "Agents" (small, specialized programs) to evaluate every transaction. This makes the system faster, cheaper, and easier to understand.

*   **Triage Agent:** The "bouncer". It looks at obvious signs (like micro-charges under $1, massive amounts over $5,000, or late-night transactions). If a transaction looks completely normal, the Triage Agent approves it instantly to save time and money.
*   **Risk Scoring Agent:** The "statistician". It looks at historical patterns and features (like z-scores and PCA components) to assign a numerical risk score between 0.0 and 1.0. 
*   **Compliance Agent:** The "rule enforcer". It checks strict business policies. Did this customer make 15 transactions in the last hour? Are they suddenly shopping from a new country? It logs these policy passes, warnings, or failures.
*   **Investigation Agent (LLM):** The "detective". This is powered by an advanced Large Language Model (Azure AI Foundry / OpenAI). It is *only* called in if the transaction looks suspicious (high risk score or policy failure). It reads all the evidence and makes a final, structured decision (`approve`, `flag`, `block`, `escalate`) along with human-readable reasoning.

### 2. Cost and Privacy Guardrails
Running advanced AI can be expensive. We built specific rules to keep costs down and data safe:
*   **Cost Gating:** We don't ask the expensive Detective (Investigation Agent) to look at boring, normal transactions. The Triage Agent filters out the noise.
*   **Prompt Caching:** If exactly the same prompt is generated, the system uses a cached answer instead of calling the AI again.
*   **Privacy-First:** Raw customer data (like names or full credit card numbers) is never sent to the LLM. Furthermore, we don't even save the text we sent to the AI—we only save a cryptographic "Hash" (a scrambled fingerprint) of the prompt.

### 3. Synthetic Fraud Generator
To prove the system works, we can't just rely on normal transactions. We need bad guys. The platform includes a **Synthetic Generator** that creates fake transactions representing specific types of attacks:
*   **Card Testing:** Hackers trying many $1.00 charges to see if stolen cards work.
*   **Account Takeover (ATO):** A login from a new device in a different country making huge purchases.
*   **Velocity Attacks:** A rapid burst of 20 purchases in 60 seconds.
*   **Merchant Fraud:** A fake store processing charges and then refunding them (money laundering).

### 4. Databricks "Medallion" Data Pipeline
Data comes in messy and leaves clean, structured, and ready for analysis. 
*   **Bronze Layer:** Raw data dumped in exactly as it arrived, plus timestamps.
*   **Silver Layer:** Cleaned data (handling missing values, fixing data types).
*   **Gold Layer:** Highly refined data, calculating advanced features like `normalised_amount` or `hour_of_day`.
*   **Results Layer:** Where the Agent's final decisions and reasoning are stored for analysts to review.

---

## ⚙️ How It Works (Step-by-Step)

Here is exactly what happens when a transaction goes through the system:

**Phase 1: Data Ingestion & Setup**
1. Raw transaction data (either from the Kaggle dataset or our Synthetic Generator) is uploaded to Azure Data Lake Storage (ADLS).
2. Databricks jobs run sequentially. They pull the raw data into Bronze, clean it into Silver, and extract features into Gold Delta tables.

**Phase 2: Agent Analysis**
1. Databricks sends a batch of transactions from the Gold table to our FastAPI Agent Service.
2. The **Triage Agent** looks at it. If it's a $5 coffee at 10 AM, it scores it `0.1` and approves it immediately.
3. The **Risk Scoring Agent** reviews historical signals.
4. The **Compliance Agent** ensures the transaction doesn't violate hard rules (like spending limits).
5. If the transaction is high risk (e.g., $4,000 from a new device in a foreign country), the **Investigation Agent** packages the data into a prompt and sends it to Azure AI Foundry. The AI responds with `{"decision": "block", "reasoning": "New device, unusual geo, high amount."}`.

**Phase 3: Auditing & Review**
1. Every single step the agents took, the latency (how long it took), and the final decision is saved as an `AgentEventLog`.
2. This log is written securely to Azure Data Lake Storage as a `.jsonl` file.
3. Databricks analysts can query these results using simple SQL (found in `databricks/sql/queries.sql`) to see fraud rates, model accuracy, and why the LLM decided to block certain transactions.
