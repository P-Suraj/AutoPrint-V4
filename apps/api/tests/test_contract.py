"""Contract checks: the pieces that must agree, do. A failure here means drift."""
import re
import sys
from enum import Enum
from pathlib import Path

import psycopg2
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from app import schemas  # noqa: E402
from app.errors import CATALOG, SQL_RESULT_MAP, SQL_SUCCESS  # noqa: E402
from app.main import create_app  # noqa: E402

app = create_app(contract_only=True)

MIGRATIONS = ROOT / "supabase" / "migrations"


def sql_text() -> str:
    return "\n".join(f.read_text(encoding="utf-8") for f in sorted(MIGRATIONS.glob("*.sql")))


def test_openapi_file_is_current():
    from export_openapi import render
    committed = (ROOT / "contracts" / "openapi.json").read_text(encoding="utf-8")
    assert committed == render(), "contracts/openapi.json is stale: run scripts/export_openapi.py and commit it"


@pytest.mark.parametrize("sql_type,py_enum", [
    ("order_status", schemas.OrderStatus), ("document_status", schemas.DocumentStatus),
    ("payment_mode", schemas.PaymentMode), ("payment_status", schemas.PaymentStatus),
    ("job_status", schemas.JobStatus), ("attempt_status", schemas.AttemptStatus),
])
def test_enums_match_the_database(sql_type, py_enum):
    m = re.search(rf"CREATE TYPE ap\.{sql_type}\s+AS ENUM \((.*?)\);", sql_text(), re.S)
    assert m, f"enum {sql_type} not found in migrations"
    sql_values = re.findall(r"'([a-z_]+)'", m.group(1))
    assert sql_values == [e.value for e in py_enum], f"{sql_type} differs between SQL and schemas.py"


def test_every_sql_result_code_is_in_the_error_catalog():
    codes = set(re.findall(r"'result',\s*'([a-z_]+)'", sql_text()))
    unmapped = codes - SQL_SUCCESS - set(SQL_RESULT_MAP)
    assert not unmapped, f"SQL result codes with no API error mapping: {sorted(unmapped)}"
    for api_code in SQL_RESULT_MAP.values():
        assert api_code in CATALOG, f"{api_code} is mapped but missing from the catalog"


def test_catalog_has_no_unsafe_text_and_valid_status():
    for e in CATALOG.values():
        assert 400 <= e.http_status <= 599
        assert not re.search(r"sql|traceback|exception|postgres|supabase", e.message, re.I), e.code


def test_no_expected_failure_maps_to_http_500_except_total_mismatch():
    for sql_code, api_code in SQL_RESULT_MAP.items():
        if CATALOG[api_code].http_status == 500:
            assert sql_code == "total_mismatch"


def test_customer_wording_never_claims_printed():
    # O-8: until the Phase 1 spike proves completion evidence, no customer text says "printed".
    from app.wording import CUSTOMER_MESSAGE
    assert set(CUSTOMER_MESSAGE) == set(schemas.JobStatus), "every job status needs customer wording"
    assert CUSTOMER_MESSAGE[schemas.JobStatus.completed] == "Sent to printer."
    for status, text in CUSTOMER_MESSAGE.items():
        assert not re.search(r"printed", text, re.I), f"{status}: {text}"


def test_stub_handlers_answer_with_the_error_envelope():
    client = TestClient(app)
    r = client.post("/v1/agent/enroll", json={"enrollment_code": "ABCDEFGH", "display_name": "PC"})
    assert r.status_code == 501 and r.json() == {"error": {"code": "not_implemented", "message": "Not implemented yet."}}
    assert client.get("/health").json()["contract_version"] == schemas.CONTRACT_VERSION


def test_every_operation_has_a_unique_id_and_declares_errors():
    spec = app.openapi()
    ids = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            ids.append(op["operationId"])
            if not path.startswith("/health"):
                assert "409" in op["responses"] or "404" in op["responses"], f"{method} {path} declares no errors"
    assert len(ids) == len(set(ids))


def test_order_secret_and_device_headers_are_required_where_documented():
    spec = app.openapi()
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            names = {p["name"].lower() for p in op.get("parameters", []) if p["in"] == "header"}
            if path.startswith("/v1/orders/"):
                assert "x-order-secret" in names, f"{method} {path}"
            if path.startswith("/v1/agent/") and path != "/v1/agent/enroll":
                assert {"x-device-id", "x-device-secret"} <= names, f"{method} {path}"


def test_typescript_client_is_current(tmp_path):
    """The committed TS types must equal what the generator produces from contracts/openapi.json."""
    import shutil
    import subprocess
    tool = shutil.which("openapi-typescript", path=str(ROOT / "apps" / "web" / "node_modules" / ".bin"))
    if tool is None:
        pytest.skip("run `npm install` in apps/web to enable this check")
    out = tmp_path / "schema.d.ts"
    subprocess.run([tool, str(ROOT / "contracts" / "openapi.json"), "-o", str(out)], check=True, capture_output=True)
    committed = (ROOT / "contracts" / "clients" / "ts" / "schema.d.ts").read_text(encoding="utf-8")
    assert out.read_text(encoding="utf-8").replace("\r\n", "\n") == committed.replace("\r\n", "\n"), \
        "TypeScript client is stale: run `npm run gen:client` in apps/web and commit it"
