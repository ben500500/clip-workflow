# backend/app/models/user.py

- UserRole · class · L25-L30 — class UserRole(str, enum.Enum)
- default_data_scope_for_role · function · L52-L57 — def default_data_scope_for_role(role: str) -> str
- user_can_access_all_materials · function · L60-L65 — def user_can_access_all_materials(user: "User") -> bool
- User · class · L68-L92 — class User(Base)
- __repr__ · method · L91-L92 — def __repr__(self) -> str
- UserSession · class · L95-L117 — class UserSession(Base)
- __repr__ · method · L116-L117 — def __repr__(self) -> str
- UserPreference · class · L120-L136 — class UserPreference(Base)
- __repr__ · method · L135-L136 — def __repr__(self) -> str
