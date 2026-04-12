import json
import logging
import math
import os
import time
from io import StringIO

import azure.functions as func
import pandas as pd
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

DEFAULT_SOURCE_BLOB = "All_Diets (1).csv"
DEFAULT_CLEANED_BLOB = "All_Diets_cleaned.csv"
DIET_COLUMN_CANDIDATES = ["Diet_type", "Diet Type", "diet_type", "diet"]
TITLE_COLUMN_CANDIDATES = [
    "Recipe_name",
    "Recipe Name",
    "Recipe",
    "Title",
    "Name",
]
DETAIL_COLUMN_CANDIDATES = [
    "Cuisine_type",
    "Cuisine Type",
    "Ingredients",
    "Description",
    "Instructions",
    "Extraction_day",
]
NUTRIENT_COLUMNS = ["Protein(g)", "Carbs(g)", "Fat(g)"]
MAX_PAGE_SIZE = 50


def json_response(payload: dict, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload),
        mimetype="application/json",
        status_code=status_code,
    )


def get_container_client():
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    container_name = os.environ.get("CONTAINER_NAME", "datasets")

    if not conn_str:
        raise RuntimeError("Missing AZURE_STORAGE_CONNECTION_STRING")

    blob_service = BlobServiceClient.from_connection_string(conn_str)
    return blob_service.get_container_client(container_name)


def load_dataset():
    container_client = get_container_client()
    source_blob = os.environ.get("SOURCE_BLOB_NAME", DEFAULT_SOURCE_BLOB)
    cleaned_blob = os.environ.get("CLEANED_BLOB_NAME", DEFAULT_CLEANED_BLOB)

    candidate_blobs = []
    if cleaned_blob and cleaned_blob != source_blob:
        candidate_blobs.append(cleaned_blob)
    candidate_blobs.append(source_blob)

    last_error = None

    for blob_name in candidate_blobs:
        try:
            blob_client = container_client.get_blob_client(blob_name)
            blob_data = blob_client.download_blob().readall().decode("utf-8")
            df = pd.read_csv(StringIO(blob_data))
            return normalize_dataframe(df), blob_name
        except ResourceNotFoundError as exc:
            last_error = exc
            continue

    if last_error:
        raise last_error

    raise RuntimeError("Unable to load dataset from blob storage.")


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = normalized.columns.str.strip()

    for column in normalized.columns:
        if pd.api.types.is_object_dtype(normalized[column]) or pd.api.types.is_string_dtype(normalized[column]):
            normalized[column] = normalized[column].fillna("").astype(str).str.strip()

    return normalized


def pick_first_available(columns, candidates):
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def parse_positive_int(value, default, minimum=1, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default

    parsed = max(minimum, parsed)

    if maximum is not None:
        parsed = min(maximum, parsed)

    return parsed


def to_serializable(value):
    if pd.isna(value):
        return None

    if isinstance(value, (bool, int)):
        return value

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        rounded = round(value, 2)
        return int(rounded) if rounded.is_integer() else rounded

    return str(value)


def compute_group_mean(df: pd.DataFrame, group_column: str, value_column: str):
    if group_column not in df.columns or value_column not in df.columns:
        return []

    numeric_df = df[[group_column, value_column]].copy()
    numeric_df[value_column] = pd.to_numeric(numeric_df[value_column], errors="coerce")
    numeric_df = numeric_df.dropna(subset=[group_column, value_column])

    if numeric_df.empty:
        return []

    return (
        numeric_df.groupby(group_column, as_index=False)[value_column]
        .mean()
        .round(2)
        .to_dict(orient="records")
    )


def build_insights_payload(df: pd.DataFrame, source_blob: str, start_time: float):
    diet_column = pick_first_available(df.columns, DIET_COLUMN_CANDIDATES)

    if diet_column:
        diets = df[diet_column].value_counts().reset_index()
        diets.columns = ["Diet_type", "Count"]
        diets = diets.to_dict(orient="records")
    else:
        diets = []

    protein = compute_group_mean(df, diet_column, "Protein(g)") if diet_column else []
    carbs = compute_group_mean(df, diet_column, "Carbs(g)") if diet_column else []
    fat = compute_group_mean(df, diet_column, "Fat(g)") if diet_column else []

    available_nutrients = [column for column in NUTRIENT_COLUMNS if column in df.columns]
    numeric_metrics = {}

    for column in available_nutrients:
        numeric_metrics[column] = pd.to_numeric(df[column], errors="coerce")

    if available_nutrients:
        numeric_df = pd.DataFrame(numeric_metrics)
        correlations = numeric_df.corr().round(4).fillna(0).to_dict()
    else:
        correlations = {}

    metrics = {
        "avgProtein": to_serializable(numeric_metrics["Protein(g)"].mean()) if "Protein(g)" in numeric_metrics else None,
        "avgCarbs": to_serializable(numeric_metrics["Carbs(g)"].mean()) if "Carbs(g)" in numeric_metrics else None,
        "avgFat": to_serializable(numeric_metrics["Fat(g)"].mean()) if "Fat(g)" in numeric_metrics else None,
        "recordCount": len(df),
    }

    execution_time = round((time.time() - start_time) * 1000, 2)
    meta = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "executionTimeMs": execution_time,
        "recordCount": len(df),
        "sourceBlob": source_blob,
    }

    return {
        "diets": diets,
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
        "correlations": correlations,
        "metrics": metrics,
        "meta": meta,
    }


def get_searchable_columns(df: pd.DataFrame, diet_column: str):
    text_columns = [
        column
        for column in df.columns
        if (pd.api.types.is_object_dtype(df[column]) or pd.api.types.is_string_dtype(df[column]))
        and column != diet_column
    ]

    ordered = []
    for column in TITLE_COLUMN_CANDIDATES + DETAIL_COLUMN_CANDIDATES + text_columns:
        if column in text_columns and column not in ordered:
            ordered.append(column)

    return ordered


def build_recipe_items(df: pd.DataFrame, start_number: int = 1):
    diet_column = pick_first_available(df.columns, DIET_COLUMN_CANDIDATES)
    title_column = pick_first_available(df.columns, TITLE_COLUMN_CANDIDATES)
    detail_columns = [
        column
        for column in DETAIL_COLUMN_CANDIDATES
        if column in df.columns and column not in {diet_column, title_column}
    ]
    nutrient_columns = [column for column in NUTRIENT_COLUMNS if column in df.columns]

    ordered_columns = []
    for column in [title_column, diet_column] + detail_columns + nutrient_columns + list(df.columns):
        if column and column not in ordered_columns:
            ordered_columns.append(column)

    items = []

    for offset, (_, row) in enumerate(df.iterrows(), start=start_number):
        fields = {}
        for column in ordered_columns:
            serialized = to_serializable(row[column])
            if serialized not in (None, ""):
                fields[column] = serialized

        recipe_name = fields.get(title_column) if title_column else None
        diet_type = fields.get(diet_column) if diet_column else None
        nutrients = {column: fields[column] for column in nutrient_columns if column in fields}

        summary_parts = []
        for column in detail_columns:
            value = fields.get(column)
            if value:
                summary_parts.append(f"{column.replace('_', ' ')}: {value}")

        items.append(
            {
                "id": offset,
                "recipeName": recipe_name or f"Recipe {offset}",
                "dietType": diet_type or "Unknown",
                "summary": " | ".join(summary_parts),
                "nutrients": nutrients,
                "fields": fields,
            }
        )

    return items


def build_recipe_payload(
    df: pd.DataFrame,
    source_blob: str,
    keyword: str,
    diet_type: str,
    page: int,
    page_size: int,
):
    diet_column = pick_first_available(df.columns, DIET_COLUMN_CANDIDATES)
    searchable_columns = get_searchable_columns(df, diet_column)
    filtered_df = df.copy()

    if diet_column and diet_type and diet_type.lower() != "all":
        filtered_df = filtered_df[filtered_df[diet_column].str.casefold() == diet_type.casefold()]

    if keyword:
        keyword_mask = pd.Series(False, index=filtered_df.index)
        for column in searchable_columns:
            keyword_mask = keyword_mask | filtered_df[column].str.contains(keyword, case=False, na=False)
        filtered_df = filtered_df[keyword_mask]

    total_items = len(filtered_df)
    total_pages = max(1, math.ceil(total_items / page_size)) if total_items else 1
    current_page = min(page, total_pages)
    start_index = (current_page - 1) * page_size
    end_index = start_index + page_size
    page_df = filtered_df.iloc[start_index:end_index].copy()

    available_diet_types = []
    if diet_column:
        available_diet_types = sorted(
            {
                value
                for value in df[diet_column].dropna().astype(str).str.strip().tolist()
                if value
            },
            key=str.casefold,
        )

    return {
        "items": build_recipe_items(page_df, start_number=start_index + 1),
        "filters": {
            "dietType": diet_type or "all",
            "keyword": keyword,
            "availableDietTypes": available_diet_types,
            "searchableColumns": searchable_columns,
        },
        "pagination": {
            "page": current_page,
            "pageSize": page_size,
            "totalItems": total_items,
            "totalPages": total_pages,
            "hasPreviousPage": current_page > 1,
            "hasNextPage": current_page < total_pages,
            "returnedCount": len(page_df),
        },
        "meta": {
            "sourceBlob": source_blob,
            "returnedCount": len(page_df),
        },
    }


@app.route(route="getDietData", methods=["GET"])
def get_diet_data(req: func.HttpRequest) -> func.HttpResponse:
    start_time = time.time()

    try:
        df, source_blob = load_dataset()
        return json_response(build_insights_payload(df, source_blob, start_time))
    except Exception as exc:
        logging.error(str(exc))
        return json_response({"error": str(exc)}, status_code=500)


@app.route(route="browseRecipes", methods=["GET"])
def browse_recipes(req: func.HttpRequest) -> func.HttpResponse:
    try:
        df, source_blob = load_dataset()

        keyword = (req.params.get("keyword") or "").strip()
        diet_type = (req.params.get("dietType") or "all").strip()
        page = parse_positive_int(req.params.get("page"), default=1)
        page_size = parse_positive_int(req.params.get("pageSize"), default=10, maximum=MAX_PAGE_SIZE)

        payload = build_recipe_payload(df, source_blob, keyword, diet_type, page, page_size)
        return json_response(payload)
    except Exception as exc:
        logging.error(str(exc))
        return json_response({"error": str(exc)}, status_code=500)
