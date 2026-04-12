 # CloudComputingProj2

## Overview
This project is a cloud-based nutritional insights dashboard built for the Cloud Dashboard Development lab. The solution uses an Azure Function App to read a diet dataset from Azure Blob Storage, compute analytics, and return structured JSON to a frontend dashboard that visualizes the results. The current version also includes authenticated access so only signed-in users can reach the dashboard.

## Project Objective
The goal of Phase 2 is to move the Phase 1 local solution into Azure and demonstrate a cloud-native workflow using:
- Azure Function App for serverless backend execution
- Azure Blob Storage for cloud dataset storage
- A browser-based frontend dashboard for visualization and interaction

## Architecture
1. The diet dataset CSV is stored in Azure Blob Storage.
2. The Azure Function reads the CSV from Blob Storage.
3. The function cleans and aggregates the dataset using pandas.
4. The function returns JSON containing diet counts, average nutrients, correlations, and execution metadata.
5. The frontend fetches the Azure Function endpoint and renders charts in the browser using Chart.js.

## Project Structure
```text
CloudComputingProj2/
  backend/
    function_app.py
    host.json
    requirements.txt
  frontend/
    index.html
    script.js
    README.txt
  README.md
```

## Backend
Backend files are located in `backend/`.

### Main file
- `function_app.py`: Azure Function entry point

### Backend responsibilities
- Connect to Azure Blob Storage using `AZURE_STORAGE_CONNECTION_STRING`
- Read the `All_Diets (1).csv` dataset from the configured blob container
- Compute:
  - diet counts
  - average protein by diet type
  - average carbs by diet type
  - average fat by diet type
  - nutrient correlations
  - execution metadata
- Return the results as JSON

### Required environment variables
- `AZURE_STORAGE_CONNECTION_STRING`
- `DATASET_CONTAINER_NAME` (optional, defaults to `datasets`)
- `USERS_TABLE_NAME` (optional, defaults to `userprofiles`)
- `SESSION_SECRET` (required for production; used to sign login sessions)
- `SESSION_TTL_SECONDS` (optional, defaults to `86400`)
- `FRONTEND_URL` (frontend origin used after GitHub OAuth sign-in)
- `GITHUB_CLIENT_ID` (required for GitHub OAuth)
- `GITHUB_CLIENT_SECRET` (required for GitHub OAuth)
- `GITHUB_REDIRECT_URI` (optional; callback URL for GitHub OAuth)

## Frontend
Frontend files are located in `frontend/`.

### Main files
- `index.html`: dashboard UI
- `script.js`: API integration and chart rendering

### Frontend responsibilities
- Show register/login forms before the dashboard is visible
- Support GitHub OAuth sign-in
- Persist the signed-in session token in the browser
- Call the deployed Azure Function endpoint with authentication
- Render live dashboard data
- Display multiple visualizations
- Show execution metadata such as timestamp and execution time
- Allow the user to refresh the dashboard data
- Show the logged-in user's name and provide logout

## Visualizations Included
The dashboard includes at least three required visualizations:
- Bar chart for average protein by diet type
- Pie chart for carbohydrate distribution
- Scatter plot for protein vs carbohydrates
- Heatmap for nutrient correlations

## Deployment Links
Replace the placeholders below with your actual deployed links before submission.

- Azure Function URL: `https://project2functionapp.azurewebsites.net/api/getDietData`
- Frontend Deployment URL: `https://proud-coast-06e36830f.4.azurestaticapps.net/`
- GitHub Repository URL: `https://github.com/cryden05/CloudComputingProj2`

## How the Dashboard Works
1. A user opens the dashboard page.
2. The frontend sends a request to the deployed Azure Function.
3. The Azure Function reads the dataset from Azure Blob Storage.
4. The function calculates insights and returns JSON.
5. The frontend updates the visualizations and metadata using the returned data.

## Technologies Used
- HTML
- JavaScript
- Chart.js
- Python
- Azure Functions
- Azure Blob Storage
- Azure Table Storage
- pandas

## Setup Notes
### Backend
Install dependencies from `backend/requirements.txt` and configure Azure Function settings with the correct storage connection string.

### Frontend
Make sure the `API_URL` in `frontend/script.js` points to the deployed Azure Function endpoint.

## Testing Checklist
- Users can register with email and password
- Passwords are stored as hashes, not plain text
- Users can sign in with GitHub OAuth
- User profiles are stored in table storage
- Unauthenticated requests to the dashboard API are rejected
- The frontend hides the dashboard until login succeeds
- The logged-in user name is displayed with a logout button
- Azure Function endpoint returns JSON successfully
- Dataset is read from Azure Blob Storage
- Dashboard loads live data on page load
- Charts update from backend data instead of placeholder values
- Execution metadata is shown on the page
- Frontend is publicly accessible

## Challenges Encountered
Possible issues encountered during development included:
- integrating the frontend with the deployed Azure Function
- placeholder chart data appearing before live API data loaded
- configuring Azure storage connection strings correctly
- ensuring the deployed function route matched the frontend request URL

## Submission Deliverables
- Deployed Azure Function URL
- Deployed frontend URL
- GitHub repository containing frontend and backend code
- Documentation PDF with architecture explanation and screenshots
