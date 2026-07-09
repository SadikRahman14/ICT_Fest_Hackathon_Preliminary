Bug: Duplicate username during registration returns success instead of error

File: app/routers/auth.py
Endpoint: POST /auth/register

Problem

According to the API contract, when a user tries to register with a username that already exists inside the same organization, the API must return:

409 USERNAME_TAKEN

The business rule says: unknown organization creates the first user as admin; known organization adds new users as member; but duplicate username within the same organization must be rejected.

Original buggy behavior

The original code checked whether the username already existed, but instead of raising an error, it returned the existing user as a successful response.

Example:
```json
{
  "org_name": "acme",
  "username": "alice",
  "password": "pass123"
}
```
First request correctly creates alice.

But sending the same request again returned the existing alice user with success status, instead of rejecting the duplicate registration.

Why this is wrong:
This violates the registration rule because duplicate usernames inside the same organization should not be accepted. It also makes the API misleading because the user may think a new account was created, when actually the old account was returned.

Fix:
Changed the duplicate username handling from returning the existing user to raising an application error:

if existing is not None:
    raise AppError(409, "USERNAME_TAKEN", "Username already taken")
Additional safety fix

Added IntegrityError handling around user creation so that if two duplicate registration requests happen concurrently, the database uniqueness error is converted into the correct API response:

```py
except IntegrityError:
    db.rollback()
    raise AppError(409, "USERNAME_TAKEN", "Username already taken")
```


Bug: Logout does not revoke access token
After logout, the same access token should stop working. But in the code, logout revokes using jti, while token checking mistakenly checks sub
Check : app/auth.py


Bug: "Access tokens expire in exactly 900 seconds."
900 minutes to 900 seconds converted in app/auth.py

Bug: Duplicate username registration returns success
Same org_name + same username should return 409 USERNAME_TAKEN. But the code was returning the existing user instead of showing an error.
Check: app/routers/auth.py

Bug: Registration transaction issue
New organization and first admin user were committed separately. Changed it so the org ID is created using db.flush() and then the org + admin user are committed safely together.
Check: app/routers/auth.py

Bug: Registration crash on duplicate/concurrent request
If two same usernames were registered at the same time, database IntegrityError could happen. Added IntegrityError catch and returned 409 USERNAME_TAKEN instead of server crash.
Check: app/routers/auth.py