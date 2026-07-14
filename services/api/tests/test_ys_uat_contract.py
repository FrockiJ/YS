from pathlib import Path
import unittest


class YsUatContractTests(unittest.TestCase):
    def test_compose_only_exposes_dynamically_assigned_web_port(self) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        compose = (repository_root / "docker-compose.uat.yml").read_text(encoding="utf-8")

        self.assertIn('"${YS_UAT_WEB_BIND_ADDRESS:-127.0.0.1}::80"', compose)
        for service in ("api", "extract-worker", "postgres", "redis"):
            section = compose.split(f"  {service}:", 1)[1].split("\n  ", 1)[0]
            self.assertNotIn("ports:", section)

    def test_release_lock_targets_frontend_uat_branch(self) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        lock = (repository_root / "deploy" / "release.lock.json").read_text(encoding="utf-8")

        self.assertIn('"branch": "ys-vue-uat"', lock)
        self.assertNotIn("TO_BE_SET", lock)


if __name__ == "__main__":
    unittest.main()
