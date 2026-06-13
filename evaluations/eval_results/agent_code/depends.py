from typing import Annotated
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

app = FastAPI()

# Define the pagination dependency function.
# This function will take 'skip' and 'limit' as query parameters,
# with default values as specified in the task (0 and 10 respectively).
# It returns these values as a dictionary.
# Grounding: [2, 4, 5, 8, 10] illustrate defining such a dependency function.
async def pagination_dependency(skip: int = 0, limit: int = 10):
    """
    A dependency that provides skip and limit pagination parameters.
    These are automatically parsed from query parameters.
    """
    return {"skip": skip, "limit": limit}

# Define the GET /items endpoint.
# It uses Depends() to inject the pagination parameters from the dependency.
# The dependency is passed to the path operation function via its parameter.
# Grounding: [2, 5, 8] show how to declare a dependency in a path operation.
# The endpoint returns the dictionary resolved by the dependency.
@app.get("/items/")
async def read_items(pagination: Annotated[dict, Depends(pagination_dependency)]):
    """
    Retrieves pagination parameters using a dependency.
    The resolved dictionary from the dependency is returned directly.
    """
    return pagination

# Initialize the TestClient for in-process testing.
# Grounding: [6, 9] demonstrate the use of TestClient.
client = TestClient(app)

print("--- Testing Valid Requests ---")

# Test Case 1: No query parameters provided, should use defaults (skip=0, limit=10).
# Grounding: [1] explains default query parameter behavior.
response_default = client.get("/items/")
print(f"GET /items/ (default): Status Code {response_default.status_code}, JSON: {response_default.json()}")
assert response_default.status_code == 200, "Expected status code 200 for default request."
assert response_default.json() == {"skip": 0, "limit": 10}, "Expected default skip and limit."

# Test Case 2: Custom 'skip' and 'limit' values provided in the query string.
# This verifies 'skip' (and 'limit') are correctly read from the query string.
# Grounding: [1] shows how query parameters are read from the URL.
response_custom = client.get("/items/?skip=5&limit=20")
print(f"GET /items/?skip=5&limit=20: Status Code {response_custom.status_code}, JSON: {response_custom.json()}")
assert response_custom.status_code == 200, "Expected status code 200 for custom parameters."
assert response_custom.json() == {"skip": 5, "limit": 20}, "Expected custom skip and limit values."

# Test Case 3: Only 'skip' provided, 'limit' should use its default.
# Grounding: [1] describes how specific query parameters override defaults.
response_skip_only = client.get("/items/?skip=100")
print(f"GET /items/?skip=100: Status Code {response_skip_only.status_code}, JSON: {response_skip_only.json()}")
assert response_skip_only.status_code == 200, "Expected status code 200 for partial custom parameters."
assert response_skip_only.json() == {"skip": 100, "limit": 10}, "Expected custom skip and default limit."

print("\n--- Testing Invalid Request ---")

# Test Case 4: Invalid type for 'skip' (e.g., "abc" instead of an integer).
# FastAPI automatically handles data parsing and validation for type-hinted parameters.
# Grounding: [1] mentions automatic data conversion and validation for query parameters.
response_invalid = client.get("/items/?skip=abc")
print(f"GET /items/?skip=abc: Status Code {response_invalid.status_code}, JSON: {response_invalid.json()}")
assert response_invalid.status_code == 422, "Expected status code 422 for validation error."
assert "detail" in response_invalid.json(), "Expected 'detail' field in validation error response."
# Fix: The error message from Pydantic/FastAPI might vary slightly across versions.
# We'll check for a more general part of the error message: "valid integer".
assert any("valid integer" in error["msg"] for error in response_invalid.json()["detail"]), \
    "Expected error message indicating an invalid integer type."