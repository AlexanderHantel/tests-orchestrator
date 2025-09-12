# Tests Orchestrator

This repository serves as an **orchestrator** for downstream GitHub repositories [db-test-scripts-automatisation](https://github.com/AlexanderHantel/db-test-scripts-automatisation) and [db-test-java](https://github.com/AlexanderHantel/db-test-java). It triggers their CI workflows, collects their test artifacts, aggregates the results, and publishes a combined report directly inside the GitHub Actions interface.

## Features

- Triggers workflows in multiple dependent repositories using the GitHub API  
- Downloads and parses XML artifacts from each downstream run  
- Aggregates results into a single Markdown report  
- Displays the summary report directly in the **Actions Summary** tab  
- Uploads the same report as a downloadable artifact (`orchestrator-report`)  

## How It Works

1. **Workflow Dispatch** – The orchestrator uses a personal access token to send  
   `workflow_dispatch` events to specified repositories.  
2. **Polling** – It waits until all downstream workflows complete.  
3. **Artifact Collection** – It downloads their artifacts and parses XML files.  
4. **Report Generation** – It aggregates total test counts, failures, and failure messages.  
5. **Summary Display** – It publishes the aggregated results to the Actions Summary tab.

## Requirements

- **Personal Access Token** with `workflow` and `repo` permissions stored as  
  `REPO_DISPATCH_TOKEN` in this repository’s secrets.  
- Each downstream repository **must**:
  - Contain a workflow with `on: workflow_dispatch` enabled.
  - Upload its test results as a artifact.

## Running the Workflow

1. Go to the **Actions** tab of this repository.  
2. Select **Orchestrator CI** from the list of workflows.  
3. Click **Run workflow** → choose a branch (e.g., `main`) → **Run workflow**.  

## Viewing the Report

- After the workflow finishes, open the **Actions** tab → select the latest run →  
  **Summary**. The aggregated Markdown report is displayed inline.  
- You can also download the raw Markdown file:
  1. Inside the workflow run, expand **Artifacts**.
  2. Download `orchestrator-report` to view the full report locally.
