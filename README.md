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
2. A blob-triggered Azure Function watches `All_Diets.csv` and runs the cleaning pipeline only when the source blob changes.
3. The pipeline saves a cleaned CSV and precomputes JSON results for dashboard insights and recipe browsing.
4. The precomputed artifacts are stored back in Blob Storage as cache blobs.
5. HTTP requests read the cache instead of recalculating analytics on every request.
6. The frontend fetches the Azure Function endpoint and renders charts in the browser using Chart.js.

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
- Detect source blob changes using the source blob `etag`
- Clean the source dataset once per source-file update
- Save the cleaned dataset as `All_Diets_cleaned.csv`
- Precompute:
  - diet counts
  - average protein by diet type
  - average carbs by diet type
  - average fat by diet type
  - nutrient correlations
  - recipe browse index
  - execution metadata for the pipeline
- Store results in cache blobs
- Return cached results as JSON for later requests

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
- `SOURCE_BLOB_NAME` (optional, defaults to `All_Diets.csv`)
- `CLEANED_BLOB_NAME` (optional, defaults to `All_Diets_cleaned.csv`)
- `INSIGHTS_CACHE_BLOB_NAME` (optional, defaults to `cache/diet_insights.json`)
- `RECIPES_CACHE_BLOB_NAME` (optional, defaults to `cache/recipe_index.json`)
- `PIPELINE_STATUS_BLOB_NAME` (optional, defaults to `cache/pipeline_status.json`)

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
2. If the dataset has changed, the blob trigger refreshes the cleaned CSV and cache blobs once.
3. The frontend sends a request to the deployed Azure Function.
4. The Azure Function reads the precomputed cache blobs instead of recalculating from the source CSV.
5. The frontend updates the visualizations and metadata using the cached JSON response.

## Cache and Trigger Endpoints
- `GET /api/getDietData`: returns cached dashboard analytics
- `GET /api/browseRecipes`: returns cached recipe data with request-time filtering and pagination
- `GET /api/cacheStatus`: returns the latest pipeline metadata so you can demo the current cached source `etag`, source blob, and last pipeline run

## Demo Flow For Performance / Backend Optimization
1. Upload or modify `All_Diets.csv` in the configured blob container.
2. Wait for the blob trigger to run once and refresh the cache.
3. Open `GET /api/cacheStatus` and note the `sourceEtag` and `pipelineGeneratedAt` values.
4. Call `GET /api/getDietData` two or more times.
5. Show that the response metadata includes `requestServedFromCache: true` and does not require recalculation.
6. Modify the CSV again and repeat the check to show the `sourceEtag` changes and the pipeline runs one more time.

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
- Blob trigger runs when the source CSV changes
- Cleaned CSV blob is written successfully
- Cache blobs are written successfully
- Dashboard loads live data on page load
- Charts update from backend data instead of placeholder values
- Cache metadata is shown in API responses
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
