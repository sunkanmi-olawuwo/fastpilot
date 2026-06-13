from typing import Any, Union

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field # Removed EmailStr as it caused ModuleNotFoundError
# The traceback indicated ModuleNotFoundError: No module named 'email_validator'.
# EmailStr from Pydantic requires the 'email_validator' package.
# To resolve this within the given constraints (stdlib + fastapi + pydantic only, no pip install),
# we will change EmailStr to a regular str for the email field.
# This prevents Pydantic from trying to import the missing 'email_validator'.

# [1], [7], [10] Define input and output models for user data.
# UserIn includes the password for input.
class UserIn(BaseModel):
    username: str
    password: str
    email: str # Changed from EmailStr to str to resolve ModuleNotFoundError
    full_name: Union[str, None] = None

# UserOut omits the password field for the response.
# We can achieve this by inheriting from UserIn and explicitly excluding the password,
# or by simply defining a new model without it. The context suggests both.
# Option 1: Define UserOut without the password field directly (as shown in [1])
class UserOut(BaseModel):
    username: str
    email: str # Changed from EmailStr to str to resolve ModuleNotFoundError
    full_name: Union[str, None] = None

# Option 2: Inherit and use Field(..., exclude=True) (as shown in [2], [3])
# This approach is also valid for explicit exclusion, but for simplicity
# and direct alignment with [1], we'll use Option 1 for the main example.
# class UserOutAlternative(UserIn):
#     password: SecretStr = Field(..., exclude=True)

app = FastAPI()

@app.post("/users/", response_model=UserOut) # [1], [4], [5], [6]
async def create_user(user: UserIn) -> Any:
    """
    Creates a new user and returns their public profile,
    omitting sensitive information like the password.
    """
    # In a real application, you would hash the password and save the user to a database.
    # For this example, we just return the input user object,
    # and FastAPI's response_model will handle the filtering.
    return user

# Exercise the API
client = TestClient(app)

# Test case 1: Valid user creation
print("--- Testing valid user creation ---")
valid_user_data = {
    "username": "testuser",
    "password": "securepassword123",
    "email": "test@example.com",
    "full_name": "Test User"
}
response = client.post("/users/", json=valid_user_data)

print(f"Status Code: {response.status_code}")
print(f"Response Body: {response.json()}")

assert response.status_code == 200
assert "password" not in response.json() # Verify password is not in the response
assert response.json()["username"] == valid_user_data["username"]
assert response.json()["email"] == valid_user_data["email"]
assert response.json()["full_name"] == valid_user_data["full_name"]
print("ASSERTION PASSED: Valid user creation, password omitted.")

# Test case 2: Invalid user creation (missing required field 'username')
print("\n--- Testing invalid user creation (missing username) ---")
invalid_user_data = {
    "password": "anothersecret",
    "email": "invalid@example.com"
}
response = client.post("/users/", json=invalid_user_data)

print(f"Status Code: {response.status_code}")
print(f"Response Body: {response.json()}")

assert response.status_code == 422 # FastAPI returns 422 for validation errors
assert "detail" in response.json()
assert any("username" in error["loc"] for error in response.json()["detail"])
print("ASSERTION PASSED: Invalid user creation handled with 422 status and error details.")