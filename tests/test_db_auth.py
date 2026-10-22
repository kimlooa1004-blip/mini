import unittest

import helpers
import auth
import db

RECIPE = {"title": "계란말이", "servings": 2, "cook_time_min": 15,
          "have": ["계란"], "missing": ["식용유"], "steps": ["풀기", "굽기"]}


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = helpers.temp_db()
        auth._fails.clear()

    def tearDown(self):
        self._dir.cleanup()


class DbTest(Base):
    def test_recipe_roundtrip_and_order(self):
        uid = auth.signup("a@x.com", "password1", "에이")["id"]
        first = db.save_recipe(uid, RECIPE)
        second = db.save_recipe(uid, {**RECIPE, "title": "둘째"})
        got = db.list_recipes(uid)
        self.assertEqual([r["id"] for r in got], [second, first])
        self.assertEqual(got[1]["steps"], ["풀기", "굽기"])

    def test_other_users_cannot_read_or_delete(self):
        a = auth.signup("a@x.com", "password1", "에이")["id"]
        b = auth.signup("b@x.com", "password1", "비")["id"]
        rid = db.save_recipe(a, RECIPE)
        self.assertIsNone(db.get_recipe(b, rid))
        self.assertFalse(db.delete_recipe(b, rid))
        self.assertEqual(len(db.list_recipes(a)), 1)
        self.assertTrue(db.delete_recipe(a, rid))
        self.assertEqual(db.list_recipes(a), [])

    def test_profile_defaults_and_update(self):
        uid = auth.signup("a@x.com", "password1", "에이")["id"]
        self.assertEqual(db.get_profile(uid), {"nickname": "에이", "diet": "", "allergies": [], "dislikes": []})
        db.update_profile(uid, "새닉", ["땅콩"], ["오이"], "채식")
        self.assertEqual(db.get_profile(uid),
                         {"nickname": "새닉", "diet": "채식", "allergies": ["땅콩"], "dislikes": ["오이"]})

    def test_sql_injection_text_is_just_data(self):
        uid = auth.signup("a@x.com", "password1", "에이")["id"]
        evil = "x'); DROP TABLE recipes;--"
        db.save_recipe(uid, {**RECIPE, "title": evil})
        self.assertEqual(db.list_recipes(uid)[0]["title"], evil)

    def test_deleting_user_cascades(self):
        uid = auth.signup("a@x.com", "password1", "에이")["id"]
        db.save_recipe(uid, RECIPE)
        with db.connect() as c:
            c.execute("DELETE FROM users WHERE id = ?", (uid,))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM recipes").fetchone()[0], 0)


class AuthTest(Base):
    def test_password_is_hashed_not_stored(self):
        auth.signup("a@x.com", "password1", "에이")
        row = db.get_user_by_email("a@x.com")
        self.assertNotIn("password1", row["password_hash"])
        self.assertTrue(row["password_hash"].startswith("$2"))

    def test_signup_validation_messages(self):
        for args, part in ((("bad", "password1", "n"), "이메일"), (("a@x.com", "short", "n"), "8자"),
                           (("a@x.com", "password1", ""), "닉네임"), (("a@x.com", "p" * 80, "n"), "너무 깁니다")):
            with self.assertRaises(auth.AuthError) as cm:
                auth.signup(*args)
            self.assertIn(part, str(cm.exception))

    def test_duplicate_email_case_insensitive(self):
        auth.signup("a@x.com", "password1", "에이")
        with self.assertRaises(auth.AuthError):
            auth.signup(" A@X.com ", "password1", "또")

    def test_login_success_returns_no_hash(self):
        auth.signup("a@x.com", "password1", "에이")
        user = auth.login("A@x.com", "password1")
        self.assertEqual(set(user), {"id", "email", "nickname"})

    def test_wrong_password_and_unknown_email_look_identical(self):
        auth.signup("a@x.com", "password1", "에이")
        msgs = set()
        for email, pw in (("a@x.com", "wrongpass1"), ("nobody@x.com", "password1")):
            with self.assertRaises(auth.AuthError) as cm:
                auth.login(email, pw)
            msgs.add(str(cm.exception))
        self.assertEqual(msgs, {auth.BAD_LOGIN})

    def test_lockout_after_repeated_failures_then_expires(self):
        auth.signup("a@x.com", "password1", "에이")
        t = [1000.0]
        for _ in range(auth.MAX_FAILS):
            with self.assertRaises(auth.AuthError):
                auth.login("a@x.com", "nope-nope", now=lambda: t[0])
        with self.assertRaises(auth.AuthError) as cm:  # even the right password is refused
            auth.login("a@x.com", "password1", now=lambda: t[0])
        self.assertIn("너무 많습니다", str(cm.exception))
        t[0] += auth.LOCK_SECONDS + 1
        self.assertEqual(auth.login("a@x.com", "password1", now=lambda: t[0])["email"], "a@x.com")


if __name__ == "__main__":
    unittest.main()
