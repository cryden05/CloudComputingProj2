import json
import logging
import math
import os
import time
from io import StringIO

import azure.functions as func
import pandas as pd
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

DEFAULT_SOURCE_BLOB = "All_Diets.csv"
LEGACY_SOURCE_BLOB = "All_Diets (1).csv"
DEFAULT_CLEANED_BLOB = "All_Diets_cleaned.csv"
DEFAULT_INSIGHTS_CACHE_BLOB = "cache/diet_insights.json"
DEFAULT_RECIPES_CACHE_BLOB = "cache/recipe_index.json"
DEFAULT_PIPELINE_STATUS_BLOB = "cache/pipeline_status.json"
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


def utc_now_string() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_container_client():
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    container_name = os.environ.get("DATASET_CONTAINER_NAME", "datasets")

    if not conn_str:
        raise RuntimeError("Missing AZURE_STORAGE_CONNECTION_STRING")

    blob_service = BlobServiceClient.from_connection_string(conn_str)
    return blob_service.get_container_client(container_name)


def get_setting(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


def get_source_blob_candidates():
    primary = get_setting("SOURCE_BLOB_NAME", DEFAULT_SOURCE_BLOB)
    candidates = [primary]

    if primary != LEGACY_SOURCE_BLOB:
        candidates.append(LEGACY_SOURCE_BLOB)

    return candidates


def get_cleaned_blob_name() -> str:
    return get_setting("CLEANED_BLOB_NAME", DEFAULT_CLEANED_BLOB)


def get_insights_cache_blob_name() -> str:
    return get_setting("INSIGHTS_CACHE_BLOB_NAME", DEFAULT_INSIGHTS_CACHE_BLOB)


def get_recipes_cache_blob_name() -> str:
    return get_setting("RECIPES_CACHE_BLOB_NAME", DEFAULT_RECIPES_CACHE_BLOB)


def get_pipeline_status_blob_name() -> str:
    return get_setting("PIPELINE_STATUS_BLOB_NAME", DEFAULT_PIPELINE_STATUS_BLOB)


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = normalized.columns.str.strip()

    for column in normalized.columns:
        if pd.api.types.is_object_dtype(normalized[column]) or pd.api.types.is_string_dtype(normalized[column]):
            normalized[column] = normalized[column].fillna("").astype(str).str.strip()

    return normalized


def load_source_dataframe(container_client):
    last_error = None

    for blob_name in get_source_blob_candidates():
        try:
            blob_client = container_client.get_blob_client(blob_name)
            blob_data = blob_client.download_blob().readall().decode("utf-8")
            df = pd.read_csv(StringIO(blob_data))
            properties = blob_client.get_blob_properties()
            return normalize_dataframe(df), blob_name, properties
        except ResourceNotFoundError as exc:
            last_error = exc
            continue

    if last_error:
        raise last_error

    raise RuntimeError("Unable to load dataset from blob storage.")


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


def build_pipeline_meta(
    source_blob: str,
    source_etag: str,
    source_last_modified,
    pipeline_started_at: str,
    pipeline_duration_ms: float,
    trigger_reason: str,
):
    return {
        "sourceBlob": source_blob,
        "sourceEtag": source_etag,
        "sourceLastModified": source_last_modified.isoformat() if source_last_modified else None,
        "pipelineGeneratedAt": pipeline_started_at,
        "pipelineDurationMs": round(pipeline_duration_ms, 2),
        "timestamp": pipeline_started_at,
        "executionTimeMs": round(pipeline_duration_ms, 2),
        "triggerReason": trigger_reason,
        "cacheState": "fresh",
    }


def build_insights_payload(df: pd.DataFrame, pipeline_meta: dict):
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

    return {
        "diets": diets,
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
        "correlations": correlations,
        "metrics": metrics,
        "meta": {
            **pipeline_meta,
            "recordCount": len(df),
        },
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


def build_recipe_cache(df: pd.DataFrame, pipeline_meta: dict):
    diet_column = pick_first_available(df.columns, DIET_COLUMN_CANDIDATES)
    searchable_columns = get_searchable_columns(df, diet_column)
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
        "items": build_recipe_items(df),
        "filters": {
            "availableDietTypes": available_diet_types,
            "searchableColumns": searchable_columns,
        },
        "meta": {
            **pipeline_meta,
            "recordCount": len(df),
        },
    }


def build_recipe_payload_from_cache(recipe_cache: dict, keyword: str, diet_type: str, page: int, page_size: int):
    items = recipe_cache.get("items", [])
    filters = recipe_cache.get("filters", {})
    searchable_columns = filters.get("searchableColumns", [])
    normalized_keyword = keyword.casefold()
    normalized_diet_type = diet_type.casefold()

    filtered_items = items

    if diet_type and normalized_diet_type != "all":
        filtered_items = [
            item
            for item in filtered_items
            if str(item.get("dietType", "")).casefold() == normalized_diet_type
        ]

    if keyword:
        def matches(item):
            fields = item.get("fields", {})
            for column in searchable_columns:
                value = fields.get(column)
                if value and normalized_keyword in str(value).casefold():
                    return True
            return False

        filtered_items = [item for item in filtered_items if matches(item)]

    total_items = len(filtered_items)
    total_pages = max(1, math.ceil(total_items / page_size)) if total_items else 1
    current_page = min(page, total_pages)
    start_index = (current_page - 1) * page_size
    end_index = start_index + page_size
    page_items = filtered_items[start_index:end_index]

    return {
        "items": page_items,
        "filters": {
            "dietType": diet_type or "all",
            "keyword": keyword,
            "availableDietTypes": filters.get("availableDietTypes", []),
            "searchableColumns": searchable_columns,
        },
        "pagination": {
            "page": current_page,
            "pageSize": page_size,
            "totalItems": total_items,
            "totalPages": total_pages,
            "hasPreviousPage": current_page > 1,
            "hasNextPage": current_page < total_pages,
            "returnedCount": len(page_items),
        },
        "meta": {
            **recipe_cache.get("meta", {}),
            "returnedCount": len(page_items),
        },
    }


def upload_text_blob(container_client, blob_name: str, content: str, content_type: str):
    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(
        content,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
    )


def upload_json_blob(container_client, blob_name: str, payload: dict):
    upload_text_blob(container_client, blob_name, json.dumps(payload), "application/json")


def read_json_blob(container_client, blob_name: str) -> dict:
    blob_client = container_client.get_blob_client(blob_name)
    blob_data = blob_client.download_blob().readall().decode("utf-8")
    return json.loads(blob_data)


def build_pipeline_status(
    pipeline_meta: dict,
    cleaned_blob: str,
    insights_cache_blob: str,
    recipes_cache_blob: str,
):
    return {
        **pipeline_meta,
        "cleanedDataBlob": cleaned_blob,
        "insightsCacheBlob": insights_cache_blob,
        "recipesCacheBlob": recipes_cache_blob,
    }


def refresh_pipeline_from_source(trigger_reason: str):
    pipeline_start = time.time()
    pipeline_started_at = utc_now_string()
    container_client = get_container_client()
    df, source_blob, properties = load_source_dataframe(container_client)
    cleaned_blob = get_cleaned_blob_name()
    insights_cache_blob = get_insights_cache_blob_name()
    recipes_cache_blob = get_recipes_cache_blob_name()

    pipeline_meta = build_pipeline_meta(
        source_blob=source_blob,
        source_etag=properties.etag,
        source_last_modified=properties.last_modified,
        pipeline_started_at=pipeline_started_at,
        pipeline_duration_ms=0,
        trigger_reason=trigger_reason,
    )

    upload_text_blob(container_client, cleaned_blob, df.to_csv(index=False), "text/csv")
    pipeline_meta["pipelineDurationMs"] = round((time.time() - pipeline_start) * 1000, 2)
    insights_payload = build_insights_payload(df, pipeline_meta)
    recipes_payload = build_recipe_cache(df, pipeline_meta)

    upload_json_blob(container_client, insights_cache_blob, insights_payload)
    upload_json_blob(container_client, recipes_cache_blob, recipes_payload)

    status_payload = build_pipeline_status(
        pipeline_meta=pipeline_meta,
        cleaned_blob=cleaned_blob,
        insights_cache_blob=insights_cache_blob,
        recipes_cache_blob=recipes_cache_blob,
    )
    upload_json_blob(container_client, get_pipeline_status_blob_name(), status_payload)
    return status_payload


def ensure_cached_pipeline():
    container_client = get_container_client()
    _, source_blob, properties = load_source_dataframe(container_client)

    try:
        status = read_json_blob(container_client, get_pipeline_status_blob_name())
        expected_etag = status.get("sourceEtag")
        cache_blobs = [
            status.get("insightsCacheBlob") or get_insights_cache_blob_name(),
            status.get("recipesCacheBlob") or get_recipes_cache_blob_name(),
            status.get("cleanedDataBlob") or get_cleaned_blob_name(),
        ]

        for blob_name in cache_blobs:
            container_client.get_blob_client(blob_name).get_blob_properties()

        if expected_etag == properties.etag and status.get("sourceBlob") == source_blob:
            return status
    except ResourceNotFoundError:
        logging.info("Cache missing; rebuilding pipeline artifacts.")
    except Exception as exc:
        logging.warning("Failed to validate cache status: %s", str(exc))

    return refresh_pipeline_from_source("source-changed-or-cache-missing")


def load_cached_insights():
    container_client = get_container_client()
    return read_json_blob(container_client, get_insights_cache_blob_name())


def load_cached_recipes():
    container_client = get_container_client()
    return read_json_blob(container_client, get_recipes_cache_blob_name())


def attach_request_meta(payload: dict, request_started_at: float, cache_status: str):
    meta = dict(payload.get("meta", {}))
    meta["requestTimestamp"] = utc_now_string()
    meta["requestExecutionTimeMs"] = round((time.time() - request_started_at) * 1000, 2)
    meta["requestServedFromCache"] = True
    meta["cacheStatus"] = cache_status
    payload["meta"] = meta
    return payload


@app.blob_trigger(
    arg_name="source_blob_stream",
    path="%DATASET_CONTAINER_NAME%/%SOURCE_BLOB_NAME%",
    connection="AZURE_STORAGE_CONNECTION_STRING",
)
def process_updated_dataset(source_blob_stream: func.InputStream):
    blob_name = getattr(source_blob_stream, "name", get_setting("SOURCE_BLOB_NAME", DEFAULT_SOURCE_BLOB))
    logging.info("Blob trigger received update for %s", blob_name)

    try:
        refresh_pipeline_from_source("blob-trigger")
        logging.info("Pipeline refresh completed for %s", blob_name)
    except Exception as exc:
        logging.exception("Pipeline refresh failed for %s: %s", blob_name, str(exc))
        raise


@app.route(route="getDietData", methods=["GET"])
def get_diet_data(req: func.HttpRequest) -> func.HttpResponse:
    request_start = time.time()

    try:
        ensure_cached_pipeline()
        payload = load_cached_insights()
        return json_response(attach_request_meta(payload, request_start, "hit"))
    except Exception as exc:
        logging.error(str(exc))
        return json_response({"error": str(exc)}, status_code=500)


@app.route(route="browseRecipes", methods=["GET"])
def browse_recipes(req: func.HttpRequest) -> func.HttpResponse:
    request_start = time.time()

    try:
        ensure_cached_pipeline()
        recipe_cache = load_cached_recipes()

        keyword = (req.params.get("keyword") or "").strip()
        diet_type = (req.params.get("dietType") or "all").strip()
        page = parse_positive_int(req.params.get("page"), default=1)
        page_size = parse_positive_int(req.params.get("pageSize"), default=10, maximum=MAX_PAGE_SIZE)

        payload = build_recipe_payload_from_cache(recipe_cache, keyword, diet_type, page, page_size)
        return json_response(attach_request_meta(payload, request_start, "hit"))
    except Exception as exc:
        logging.error(str(exc))
        return json_response({"error": str(exc)}, status_code=500)


@app.route(route="cacheStatus", methods=["GET"])
def cache_status(req: func.HttpRequest) -> func.HttpResponse:
    try:
        status = ensure_cached_pipeline()
        return json_response(status)
    except Exception as exc:
        logging.error(str(exc))
        return json_response({"error": str(exc)}, status_code=500)
