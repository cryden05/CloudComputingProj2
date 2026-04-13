import azure.functions as func
import base64
import hashlib
import hmac
import json
import logging
import math
import os
import secrets
import time
import urllib.parse
import urllib.request
from io import StringIO

import pandas as pd
from azure.core.exceptions import ResourceNotFoundError
from azure.data.tables import TableServiceClient, UpdateMode
from azure.storage.blob import BlobServiceClient, ContentSettings


app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

USERS_TABLE_NAME = os.environ.get("USERS_TABLE_NAME", "userprofiles")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-session-secret-change-me")
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "86400"))
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5500")

DEFAULT_SOURCE_BLOB = "All_Diets.csv"
LEGACY_SOURCE_BLOB = "All_Diets (1).csv"
DEFAULT_CLEANED_BLOB = "All_Diets_cleaned.csv"
DEFAULT_INSIGHTS_CACHE_BLOB = "cache/diet_insights.json"
DEFAULT_RECIPES_CACHE_BLOB = "cache/recipe_index.json"
DEFAULT_PIPELINE_STATUS_BLOB = "cache/pipeline_status.json"
DIET_COLUMN_CANDIDATES = ["Diet_type", "Diet Type", "diet_type", "diet"]
TITLE_COLUMN_CANDIDATES = ["Recipe_name", "Recipe Name", "Recipe", "Title", "Name"]
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
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
    )


def empty_response(status_code: int = 204) -> func.HttpResponse:
    return func.HttpResponse(
        status_code=status_code,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
    )


def is_options(req: func.HttpRequest) -> bool:
    return req.method.upper() == "OPTIONS"


def parse_json_body(req: func.HttpRequest):
    try:
        return req.get_json()
    except ValueError:
        return {}


def utc_now_string() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_storage_connection_string():
    return os.environ.get("AZURE_STORAGE_CONNECTION_STRING")


def get_setting(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


def get_container_client():
    conn_str = get_storage_connection_string()
    container_name = os.environ.get("DATASET_CONTAINER_NAME", "datasets")

    if not conn_str:
        raise RuntimeError("Missing AZURE_STORAGE_CONNECTION_STRING")

    blob_service = BlobServiceClient.from_connection_string(conn_str)
    return blob_service.get_container_client(container_name)


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


def get_table_client():
    conn_str = get_storage_connection_string()
    if not conn_str:
        raise ValueError("Missing AZURE_STORAGE_CONNECTION_STRING")

    service = TableServiceClient.from_connection_string(conn_str)
    service.create_table_if_not_exists(USERS_TABLE_NAME)
    return service.get_table_client(USERS_TABLE_NAME)


def hash_password(password: str, salt: str | None = None):
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        200000,
    )
    return salt, hashed.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    _, candidate_hash = hash_password(password, salt)
    return hmac.compare_digest(candidate_hash, expected_hash)


def encode_token(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    signature = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature_text = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
    return f"{body}.{signature_text}"


def token_debug_summary(token: str | None) -> str:
    if not token:
        return "missing"

    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    return f"len={len(token)} sha256={digest}"


def decode_token(token: str):
    try:
        body, signature = token.split(".", 1)
        expected_signature = base64.urlsafe_b64encode(
            hmac.new(
                SESSION_SECRET.encode("utf-8"),
                body.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8").rstrip("=")

        if not hmac.compare_digest(signature, expected_signature):
            return None

        padded_body = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded_body.encode("utf-8")))
        if payload.get("exp", 0) < int(time.time()):
            logging.warning("Token rejected: expired token (%s)", token_debug_summary(token))
            return None
        logging.info(
            "Token accepted (%s) sub=%s provider=%s exp=%s",
            token_debug_summary(token),
            payload.get("sub"),
            payload.get("provider"),
            payload.get("exp"),
        )
        return payload
    except Exception as exc:
        logging.warning("Token rejected: invalid token (%s): %s", token_debug_summary(token), str(exc))
        return None


def issue_session_token(user: dict) -> str:
    now = int(time.time())
    payload = {
        "sub": user["email"],
        "name": user["displayName"],
        "provider": user.get("provider", "local"),
        "iat": now,
        "exp": now + SESSION_TTL_SECONDS,
    }
    return encode_token(payload)


def public_user(user: dict) -> dict:
    return {
        "email": user["email"],
        "displayName": user["displayName"],
        "provider": user.get("provider", "local"),
        "createdAt": user.get("createdAt"),
    }


def normalize_email(value: str) -> str:
    return value.strip().lower()


def get_user_by_email(email: str):
    client = get_table_client()
    try:
        return client.get_entity(partition_key="users", row_key=normalize_email(email))
    except Exception:
        return None


def save_user(user: dict):
    client = get_table_client()
    client.upsert_entity(mode=UpdateMode.REPLACE, entity=user)


def build_user_entity(email: str, display_name: str, provider: str, password_hash="", password_salt=""):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "PartitionKey": "users",
        "RowKey": normalize_email(email),
        "email": normalize_email(email),
        "displayName": display_name.strip(),
        "provider": provider,
        "passwordHash": password_hash,
        "passwordSalt": password_salt,
        "createdAt": now,
    }


def extract_bearer_token(req: func.HttpRequest):
    auth_header = req.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


def require_authenticated_user(req: func.HttpRequest):
    token = extract_bearer_token(req)
    if not token:
        logging.info("Auth rejected: missing bearer token for %s", req.url)
        return None, json_response({"error": "Authentication required."}, status_code=401)

    payload = decode_token(token)
    if not payload:
        logging.warning("Auth rejected: invalid bearer token for %s (%s)", req.url, token_debug_summary(token))
        return None, json_response({"error": "Session expired or invalid."}, status_code=401)

    user = get_user_by_email(payload["sub"])
    if not user:
        logging.warning("Auth rejected: user profile not found for %s sub=%s", req.url, payload.get("sub"))
        return None, json_response({"error": "User profile not found."}, status_code=401)

    logging.info(
        "Auth accepted for %s sub=%s provider=%s (%s)",
        req.url,
        payload.get("sub"),
        payload.get("provider"),
        token_debug_summary(token),
    )
    return user, None


def get_github_redirect_uri(req: func.HttpRequest) -> str:
    configured = os.environ.get("GITHUB_REDIRECT_URI")
    if configured:
        return configured

    frontend_url = (os.environ.get("FRONTEND_URL") or "").strip().rstrip("/")
    if frontend_url and not frontend_url.startswith("http://localhost") and not frontend_url.startswith("http://127.0.0.1"):
        return f"{frontend_url}/api/auth/github/callback"

    forwarded_proto = req.headers.get("x-forwarded-proto", "http")
    host = req.headers.get("x-forwarded-host") or req.headers.get("host", "localhost:7071")
    return f"{forwarded_proto}://{host}/api/auth/github/callback"


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


def get_searchable_columns(df: pd.DataFrame, diet_column: str | None):
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


def attach_request_meta(payload: dict, request_started_at: float, cache_status: str, user: dict | None = None):
    meta = dict(payload.get("meta", {}))
    meta["requestTimestamp"] = utc_now_string()
    meta["requestExecutionTimeMs"] = round((time.time() - request_started_at) * 1000, 2)
    meta["requestServedFromCache"] = True
    meta["cacheStatus"] = cache_status
    payload["meta"] = meta

    if user:
        metrics = dict(payload.get("metrics", {}))
        metrics["viewer"] = user["displayName"]
        payload["metrics"] = metrics

    return payload


@app.route(route="register", methods=["POST", "OPTIONS"])
def register(req: func.HttpRequest) -> func.HttpResponse:
    if is_options(req):
        return empty_response()

    try:
        body = parse_json_body(req)
        email = normalize_email(body.get("email", ""))
        password = body.get("password", "")
        display_name = body.get("displayName", "").strip() or email.split("@")[0]

        if not email or not password:
            return json_response({"error": "Email and password are required."}, status_code=400)

        if len(password) < 8:
            return json_response({"error": "Password must be at least 8 characters."}, status_code=400)

        if get_user_by_email(email):
            return json_response({"error": "An account already exists for that email."}, status_code=409)

        salt, password_hash = hash_password(password)
        user = build_user_entity(email, display_name, "local", password_hash, salt)
        save_user(user)

        token = issue_session_token(user)
        return json_response({"token": token, "user": public_user(user)}, status_code=201)
    except Exception as exc:
        logging.exception("Register failed")
        return json_response({"error": str(exc)}, status_code=500)


@app.route(route="login", methods=["POST", "OPTIONS"])
def login(req: func.HttpRequest) -> func.HttpResponse:
    if is_options(req):
        return empty_response()

    try:
        body = parse_json_body(req)
        email = normalize_email(body.get("email", ""))
        password = body.get("password", "")

        user = get_user_by_email(email)
        if not user or user.get("provider") != "local":
            return json_response({"error": "Invalid email or password."}, status_code=401)

        if not verify_password(password, user["passwordSalt"], user["passwordHash"]):
            return json_response({"error": "Invalid email or password."}, status_code=401)

        token = issue_session_token(user)
        return json_response({"token": token, "user": public_user(user)})
    except Exception as exc:
        logging.exception("Login failed")
        return json_response({"error": str(exc)}, status_code=500)


@app.route(route="me", methods=["GET", "OPTIONS"])
def me(req: func.HttpRequest) -> func.HttpResponse:
    if is_options(req):
        return empty_response()

    user, error = require_authenticated_user(req)
    if error:
        return error

    return json_response({"user": public_user(user)})


@app.route(route="logout", methods=["POST", "OPTIONS"])
def logout(req: func.HttpRequest) -> func.HttpResponse:
    if is_options(req):
        return empty_response()

    return json_response({"message": "Logged out. Clear the client token to end the session."})


@app.route(route="auth/github/start", methods=["GET", "OPTIONS"])
def github_start(req: func.HttpRequest) -> func.HttpResponse:
    if is_options(req):
        return empty_response()

    if not GITHUB_CLIENT_ID:
        return json_response({"error": "GitHub OAuth is not configured."}, status_code=500)

    state = secrets.token_urlsafe(24)
    redirect_uri = get_github_redirect_uri(req)
    params = urllib.parse.urlencode(
        {
            "client_id": GITHUB_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
    )
    auth_url = f"https://github.com/login/oauth/authorize?{params}"
    return json_response({"authUrl": auth_url, "state": state})


def github_request(url: str, headers: dict, data: bytes | None = None):
    request = urllib.request.Request(url, headers=headers, data=data)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


@app.route(route="auth/github/callback", methods=["GET", "OPTIONS"])
def github_callback(req: func.HttpRequest) -> func.HttpResponse:
    if is_options(req):
        return empty_response()

    try:
        if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
            return json_response({"error": "GitHub OAuth is not configured."}, status_code=500)

        code = req.params.get("code", "")
        state = req.params.get("state", "")
        if not code:
            return json_response({"error": "Missing GitHub authorization code."}, status_code=400)

        redirect_uri = get_github_redirect_uri(req)
        token_payload = urllib.parse.urlencode(
            {
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            }
        ).encode("utf-8")

        token_data = github_request(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            data=token_payload,
        )

        access_token = token_data.get("access_token")
        if not access_token:
            return json_response({"error": "GitHub access token exchange failed."}, status_code=401)

        auth_headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "CloudComputingProj2",
        }
        github_user = github_request("https://api.github.com/user", headers=auth_headers)
        github_emails = github_request("https://api.github.com/user/emails", headers=auth_headers)

        primary_email = next(
            (
                email["email"]
                for email in github_emails
                if email.get("primary") and email.get("verified")
            ),
            None,
        ) or next((email["email"] for email in github_emails if email.get("verified")), None)

        if not primary_email:
            return json_response({"error": "GitHub account does not expose a verified email."}, status_code=400)

        email = normalize_email(primary_email)
        display_name = github_user.get("name") or github_user.get("login") or email.split("@")[0]
        user = get_user_by_email(email)

        if not user:
            user = build_user_entity(email, display_name, "github")
            save_user(user)

        token = issue_session_token(user)
        logging.info(
            "GitHub callback issued token for sub=%s provider=%s redirect_uri=%s frontend_url=%s (%s)",
            email,
            user.get("provider"),
            redirect_uri,
            FRONTEND_URL,
            token_debug_summary(token),
        )
        redirect_target = f"{FRONTEND_URL}?token={urllib.parse.quote(token)}&state={urllib.parse.quote(state)}"
        logging.info("GitHub callback redirecting to %s", redirect_target)
        return func.HttpResponse(status_code=302, headers={"Location": redirect_target})
    except Exception as exc:
        logging.exception("GitHub callback failed")
        return json_response({"error": str(exc)}, status_code=500)


@app.route(route="getDietData", methods=["GET", "OPTIONS"])
def get_diet_data(req: func.HttpRequest) -> func.HttpResponse:
    if is_options(req):
        return empty_response()

    user, error = require_authenticated_user(req)
    if error:
        return error

    request_start = time.time()

    try:
        ensure_cached_pipeline()
        payload = load_cached_insights()
        return json_response(attach_request_meta(payload, request_start, "hit", user))
    except Exception as exc:
        logging.error(str(exc))
        return json_response({"error": str(exc)}, status_code=500)


@app.route(route="browseRecipes", methods=["GET", "OPTIONS"])
def browse_recipes(req: func.HttpRequest) -> func.HttpResponse:
    if is_options(req):
        return empty_response()

    user, error = require_authenticated_user(req)
    if error:
        return error

    request_start = time.time()

    try:
        ensure_cached_pipeline()
        recipe_cache = load_cached_recipes()

        keyword = (req.params.get("keyword") or "").strip()
        diet_type = (req.params.get("dietType") or "all").strip()
        page = parse_positive_int(req.params.get("page"), default=1)
        page_size = parse_positive_int(req.params.get("pageSize"), default=10, maximum=MAX_PAGE_SIZE)

        payload = build_recipe_payload_from_cache(recipe_cache, keyword, diet_type, page, page_size)
        return json_response(attach_request_meta(payload, request_start, "hit", user))
    except Exception as exc:
        logging.error(str(exc))
        return json_response({"error": str(exc)}, status_code=500)


@app.route(route="cacheStatus", methods=["GET", "OPTIONS"])
def cache_status(req: func.HttpRequest) -> func.HttpResponse:
    if is_options(req):
        return empty_response()

    user, error = require_authenticated_user(req)
    if error:
        return error

    try:
        status = ensure_cached_pipeline()
        status["viewer"] = user["displayName"]
        return json_response(status)
    except Exception as exc:
        logging.error(str(exc))
        return json_response({"error": str(exc)}, status_code=500)
