from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field # [1], [8]

# 1. Build a FastAPI app
app = FastAPI()

# 2. Define the Pydantic User model with a constraint
class User(BaseModel): # [1]
    name: str # [1]
    age: int = Field(gt=0, description="The age must be greater than zero") # [8]

# 3. Create the POST /users endpoint
@app.post("/users/") # [1]
async def create_user(user: User): # [1]
    """
    Accepts a Pydantic User model and returns it.
    """
    return user

# Exercise the app in-process with TestClient
client = TestClient(app)

# --- Test Case 1: Valid Request ---
valid_user_data = {"name": "Alice", "age": 30}
print(f"--- Sending valid request: {valid_user_data} ---")
response_valid = client.post("/users/", json=valid_user_data)

# Print evidence for valid request
print(f"Valid Request Status Code: {response_valid.status_code}")
print(f"Valid Request JSON Body: {response_valid.json()}")

# Assertions for valid request
assert response_valid.status_code == 200
assert response_valid.json() == valid_user_data
print("Assertion Passed: Valid request returned 200 OK and correct data.")

# --- Test Case 2: Invalid Request (negative age) ---
invalid_user_data = {"name": "Bob", "age": -5}
print(f"\n--- Sending invalid request: {invalid_user_data} ---")
response_invalid = client.post("/users/", json=invalid_user_data)

# Print evidence for invalid request
print(f"Invalid Request Status Code: {response_invalid.status_code}")
print(f"Invalid Request JSON Body: {response_invalid.json()}")

# Assertions for invalid request
assert response_invalid.status_code == 422 # [7]
error_detail = response_invalid.json()
assert "detail" in error_detail
assert any("age" in err["loc"] and "greater than 0" in err["msg"] for err in error_detail["detail"])
# The structure of the validation error body is typically like:
# {"detail": [{"loc": ["body", "age"], "msg": "ensure this value is greater than 0", "type": "value_error.number.not_gt"}], "body": {"name": "Bob", "age": -5}} [7]
print("Assertion Passed: Invalid request returned 422 Unprocessable Entity with age validation error.")

# --- Test Case 3: Invalid Request (age zero) ---
invalid_user_data_zero = {"name": "Charlie", "age": 0}
print(f"\n--- Sending invalid request: {invalid_user_data_zero} ---")
response_invalid_zero = client.post("/users/", json=invalid_user_data_zero)

# Print evidence for invalid request
print(f"Invalid Request Status Code: {response_invalid_zero.status_code}")
print(f"Invalid Request JSON Body: {response_invalid_zero.json()}")

# Assertions for invalid request
assert response_invalid_zero.status_code == 422 # [7]
error_detail_zero = response_invalid_zero.json()
assert "detail" in error_detail_zero
assert any("age" in err["loc"] and "greater than 0" in err["msg"] for err in error_detail_zero["detail"])
print("Assertion Passed: Invalid request (age=0) returned 422 Unprocessable Entity with age validation error.")