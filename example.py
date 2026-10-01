def get_user_role(user):
    return user.get("role", "unknown")


users = [
{"name": "Ada", "role": "admin"},
{"name": "Femi"},  # missing "role" key
]

for user in users:
    print(f"{user['name']}: {get_user_role(user)}")