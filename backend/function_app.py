import azure.functions as func
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.parse
import urllib.request
from io import StringIO

import pandas as pd
from azure.data.tables import TableServiceClient, UpdateMode
from azure.storage.blob import BlobServiceClient


app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

USERS_TABLE_NAME = os.environ.get("USERS_TABLE_NAME", "userprofiles")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-session-secret-change-me")
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "86400"))
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5500")


def json_response(payload, status_code=200):
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


def empty_response(status_code=204):
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


def get_storage_connection_string():
    return os.environ.get("AZURE_STORAGE_CONNECTION_STRING")


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
            return None
        return payload
    except Exception:
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
        return None, json_response({"error": "Authentication required."}, status_code=401)

    payload = decode_token(token)
    if not payload:
        return None, json_response({"error": "Session expired or invalid."}, status_code=401)

    user = get_user_by_email(payload["sub"])
    if not user:
        return None, json_response({"error": "User profile not found."}, status_code=401)

    return user, None


def get_github_redirect_uri(req: func.HttpRequest) -> str:
    configured = os.environ.get("GITHUB_REDIRECT_URI")
    if configured:
        return configured

    forwarded_proto = req.headers.get("x-forwarded-proto", "http")
    host = req.headers.get("x-forwarded-host") or req.headers.get("host", "localhost:7071")
    return f"{forwarded_proto}://{host}/api/auth/github/callback"


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
        redirect_target = (
            f"{FRONTEND_URL}?token={urllib.parse.quote(token)}&state={urllib.parse.quote(state)}"
        )
        return func.HttpResponse(status_code=302, headers={"Location": redirect_target})
    except Exception as exc:
        logging.exception("GitHub callback failed")
        return json_response({"error": str(exc)}, status_code=500)


@app.route(route="getDietData", methods=["GET", "OPTIONS"])
def getDietData(req: func.HttpRequest) -> func.HttpResponse:
    if is_options(req):
        return empty_response()

    user, error = require_authenticated_user(req)
    if error:
        return error

    start_time = time.time()

    try:
        conn_str = get_storage_connection_string()
        container_name = os.environ.get("DATASET_CONTAINER_NAME", "datasets")

        if not conn_str:
            return json_response({"error": "Missing AZURE_STORAGE_CONNECTION_STRING"}, status_code=500)

        blob_service = BlobServiceClient.from_connection_string(conn_str)
        container_client = blob_service.get_container_client(container_name)

        blob_name = "All_Diets (1).csv"
        blob_client = container_client.get_blob_client(blob_name)
        blob_data = blob_client.download_blob().readall().decode("utf-8")

        df = pd.read_csv(StringIO(blob_data))
        df.columns = df.columns.str.strip()

        diets = df["Diet_type"].value_counts().reset_index()
        diets.columns = ["Diet_type", "Count"]
        diets = diets.to_dict(orient="records")

        protein = df.groupby("Diet_type")["Protein(g)"].mean().reset_index().to_dict(orient="records")
        carbs = df.groupby("Diet_type")["Carbs(g)"].mean().reset_index().to_dict(orient="records")
        fat = df.groupby("Diet_type")["Fat(g)"].mean().reset_index().to_dict(orient="records")

        correlations = df[["Protein(g)", "Carbs(g)", "Fat(g)"]].corr().to_dict()

        metrics = {
            "avgProtein": df["Protein(g)"].mean(),
            "avgCarbs": df["Carbs(g)"].mean(),
            "avgFat": df["Fat(g)"].mean(),
            "recordCount": len(df),
            "viewer": user["displayName"],
        }

        execution_time = round((time.time() - start_time) * 1000, 2)
        meta = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "executionTimeMs": execution_time,
            "recordCount": len(df),
        }

        result = {
            "diets": diets,
            "protein": protein,
            "carbs": carbs,
            "fat": fat,
            "correlations": correlations,
            "metrics": metrics,
            "meta": meta,
        }

        return json_response(result)
    except Exception as exc:
        logging.exception("Data fetch failed")
        return json_response({"error": str(exc)}, status_code=500)
