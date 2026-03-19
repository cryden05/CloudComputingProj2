import azure.functions as func
import logging
import os
import json
import time
import pandas as pd
from io import StringIO
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@app.route(route="getDietData", methods=["GET"])
def getDietData(req: func.HttpRequest) -> func.HttpResponse:
    start_time = time.time()

    try:
        # 1. Connect to Blob Storage
        conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        container_name = os.environ.get("CONTAINER_NAME", "datasets")

        if not conn_str:
            return func.HttpResponse("Missing AZURE_STORAGE_CONNECTION_STRING", status_code=500)

        blob_service = BlobServiceClient.from_connection_string(conn_str)
        container_client = blob_service.get_container_client(container_name)

        blob_name = "All_Diets (1).csv"

        blob_client = container_client.get_blob_client(blob_name)
        blob_data = blob_client.download_blob().readall().decode("utf-8")

        # 2. Load dataset
        df = pd.read_csv(StringIO(blob_data))
        df.columns = df.columns.str.strip()

        # 3. Diet-based aggregations
        diets = df["Diet_type"].value_counts().reset_index()
        diets.columns = ["Diet_type", "Count"]
        diets = diets.to_dict(orient="records")

        protein = df.groupby("Diet_type")["Protein(g)"].mean().reset_index().to_dict(orient="records")

        carbs = df.groupby("Diet_type")["Carbs(g)"].mean().reset_index().to_dict(orient="records")

        fat = df.groupby("Diet_type")["Fat(g)"].mean().reset_index().to_dict(orient="records")

        # 4. Correlations
        correlations = df[["Protein(g)", "Carbs(g)", "Fat(g)"]].corr().to_dict()

        # 5. Metrics
        metrics = {
            "avgProtein": df["Protein(g)"].mean(),
            "avgCarbs": df["Carbs(g)"].mean(),
            "avgFat": df["Fat(g)"].mean(),
            "recordCount": len(df)
        }

        # 6. Execution metadata
        execution_time = round((time.time() - start_time) * 1000, 2)

        meta = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "executionTimeMs": execution_time,
            "recordCount": len(df)
        }


        # 7. Final response
        result = {
            "diets": diets,
            "protein": protein,
            "carbs": carbs,
            "fat": fat,
            "correlations": correlations,
            "metrics": metrics,
            "meta": meta
        }

        return func.HttpResponse(
            json.dumps(result),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(str(e))
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json",
            status_code=500
        )