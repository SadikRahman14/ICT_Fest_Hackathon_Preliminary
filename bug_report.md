Auth - 1
If someone registers again with the same org_name and same username, the API currently returns the old user with success 201.

But the expected behavior is:

409 USERNAME_TAKEN

Auth - 2
What we did is not just making duplicate registration fail. We tried to implement these business rules:
Unknown org name → create org and make user admin.
Known org name → add user as member.
Duplicate username inside same org → 409 USERNAME_TAKEN.

Say, u sent this request:
{
  "org_name": "Sadik Org",
  "username": "sadik",
  "password": "123456"
}

The code first check if this is the first registraation for this organization. If yes, it creates the organization and makes the user an admin. 
If not, it checks if the username already exists in that organization. If it does, it returns 409 USERNAME_TAKEN. If not, it adds the user as a member of the existing organization.


