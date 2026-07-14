import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from src.api.routes_admin import _ensure_protected_user_can_be_updated, _is_protected_user
from src.core.user import UserUpdate


class ProtectedAdminUserTests(unittest.TestCase):
    def test_frocki_is_protected_case_insensitively(self):
        self.assertTrue(_is_protected_user(SimpleNamespace(username="Frocki")))
        self.assertTrue(_is_protected_user(SimpleNamespace(username="frocki")))
        self.assertFalse(_is_protected_user(SimpleNamespace(username="jopasck")))

    def test_protected_user_cannot_be_weakened_through_admin_update(self):
        protected_user = SimpleNamespace(username="Frocki")

        for payload in (
            UserUpdate(username="other"),
            UserUpdate(password="123456789"),
            UserUpdate(role="admin"),
            UserUpdate(is_active=False),
        ):
            with self.assertRaises(HTTPException) as raised:
                _ensure_protected_user_can_be_updated(protected_user, payload)
            self.assertEqual(raised.exception.status_code, 403)
            self.assertEqual(raised.exception.detail["code"], "admin.protected_user")

    def test_protected_user_profile_fields_can_still_be_edited(self):
        protected_user = SimpleNamespace(username="Frocki")

        _ensure_protected_user_can_be_updated(
            protected_user,
            UserUpdate(name="Frocki", email="frocki@local.local"),
        )

    def test_normal_admin_user_can_be_updated(self):
        normal_user = SimpleNamespace(username="jopasck")

        _ensure_protected_user_can_be_updated(
            normal_user,
            UserUpdate(password="123456789", role="admin", is_active=True),
        )


if __name__ == "__main__":
    unittest.main()
