# Documentation Outline For Submission

## 1. Title Page
- Project title: Cloud Dashboard Development Phase 2
- Course name
- Student name(s)
- Date

## 2. Project Overview
This project extends the Phase 1 local Azure Function lab into a cloud deployment. The system stores the diet dataset in Azure Blob Storage, processes it through Azure Functions, and displays the resulting analytics in a browser-based dashboard.

## 3. Objective
The purpose of this phase was to deploy a serverless cloud solution and connect it to a frontend dashboard that displays nutritional insights using live Azure-hosted data.

## 4. Cloud Architecture
Describe the architecture clearly:
- Azure Blob Storage stores the CSV dataset
- Azure Function App reads and analyzes the data
- The frontend dashboard sends HTTP requests to the Azure Function endpoint
- The frontend renders charts and metadata using the JSON response

Suggested diagram flow:
Blob Storage -> Azure Function App -> JSON API Response -> Frontend Dashboard

## 5. Azure Services Used
### Azure Function App
Used to host the serverless backend that reads and analyzes the dataset.

### Azure Blob Storage
Used to store the diet CSV dataset in the cloud.

### Frontend Hosting
Used Azure Static Web App or Azure App Service to host the dashboard frontend.

## 6. Backend Implementation
Explain that the backend:
- connects to Azure Blob Storage using environment variables
- reads the `All_Diets (1).csv` file
- uses pandas to calculate average protein, carbs, fat, diet counts, and correlations
- returns execution metadata including timestamp and execution time

## 7. Frontend Implementation
Explain that the frontend:
- calls the deployed Azure Function URL
- parses the returned JSON data
- displays a bar chart, pie chart, scatter plot, and heatmap
- shows metadata such as execution time and record count
- includes a refresh button for user interaction

## 8. Screenshots To Include
Insert screenshots for each of the following:
- Azure portal showing the Function App
- Azure portal showing the Blob Storage container
- successful Azure Function response in browser or Postman
- deployed dashboard homepage
- dashboard charts displaying live data

## 9. Challenges and Fixes
Write briefly about problems encountered and how they were resolved.
Suggested points:
- The dashboard initially displayed placeholder data instead of live API data.
- The frontend was updated to fetch live data on page load.
- The function route casing needed to match exactly between backend and frontend.
- Azure configuration variables had to be set correctly for Blob Storage access.

## 10. Results
State that the final system successfully:
- deployed the backend to Azure
- stored the dataset in Azure Blob Storage
- fetched live backend data from the frontend
- displayed multiple required visualizations
- showed execution metadata

## 11. Submission Links
Add these final links:
- Azure Function URL: [paste here]
- Frontend URL: [paste here]
- GitHub Repository URL: [paste here]

## 12. Conclusion
Summarize that the project demonstrated cloud deployment, frontend-backend integration, Azure service usage, and browser-based data visualization.
