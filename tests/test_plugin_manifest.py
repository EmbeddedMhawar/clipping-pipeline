import json
import re
import unittest
from pathlib import Path


class TestPluginManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parent.parent
        cls.manifest_path = cls.repo_root / "plugin.json"

    def test_manifest_file_exists(self):
        self.assertTrue(
            self.manifest_path.is_file(),
            f"plugin.json not found at {self.manifest_path}",
        )

    def test_manifest_json_valid_syntax(self):
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict, "plugin.json root must be a JSON object")

    def test_manifest_required_fields(self):
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        required_keys = [
            "name",
            "displayName",
            "version",
            "description",
            "author",
            "repository",
            "suggestedPrompts",
            "keywords",
        ]
        for key in required_keys:
            self.assertIn(key, data, f"Missing required key '{key}' in plugin.json")

        self.assertEqual(data["name"], "clipping-pipeline")
        self.assertEqual(data["displayName"], "Short-Form Clipping Pipeline")
        self.assertRegex(
            data["version"],
            r"^\d+\.\d+\.\d+",
            "version must be semantic versioning (e.g., 1.0.0)",
        )
        self.assertTrue(
            isinstance(data["description"], str) and len(data["description"]) > 20,
            "description must be a descriptive non-empty string",
        )
        self.assertEqual(data["author"], "Abderrahmane Mhawar")
        self.assertEqual(
            data["repository"],
            "https://github.com/EmbeddedMhawar/clipping-pipeline",
        )

        self.assertIsInstance(data["suggestedPrompts"], list)
        self.assertGreaterEqual(
            len(data["suggestedPrompts"]),
            3,
            "suggestedPrompts should contain at least 3 high-impact starter prompts",
        )
        for prompt in data["suggestedPrompts"]:
            self.assertIsInstance(prompt, str)
            self.assertTrue(len(prompt.strip()) > 0, "Prompt must not be empty")

        self.assertIsInstance(data["keywords"], list)
        expected_keywords = [
            "clipping",
            "video-editing",
            "shorts",
            "tiktok",
            "reels",
            "creator-rewards",
            "channel-warmup",
        ]
        self.assertEqual(data["keywords"], expected_keywords)

    def test_directory_structure(self):
        required_dirs = ["scripts", "references", "skills", "tests"]
        for d in required_dirs:
            dir_path = self.repo_root / d
            self.assertTrue(
                dir_path.is_dir(),
                f"Required directory '{d}' is missing at {dir_path}",
            )

    def test_skills_directories(self):
        expected_skills = [
            "clipping-pipeline",
            "clipping-guidelines",
            "clipping-channels",
        ]
        for skill in expected_skills:
            skill_dir = self.repo_root / "skills" / skill
            self.assertTrue(
                skill_dir.is_dir(),
                f"Required skill directory '{skill}' is missing at {skill_dir}",
            )
            skill_file = skill_dir / "SKILL.md"
            self.assertTrue(
                skill_file.is_file(),
                f"Required SKILL.md missing in {skill_dir}",
            )

    def test_readme_documentation(self):
        readme_path = self.repo_root / "README.md"
        self.assertTrue(readme_path.is_file(), "README.md is missing")
        content = readme_path.read_text(encoding="utf-8")

        required_sections = [
            "clipping-pipeline",
            "Installation",
            "Architecture",
            "7-Step",
            "scripts/clipping_state.py",
        ]
        for section in required_sections:
            self.assertIn(
                section,
                content,
                f"README.md must document section/keyword: '{section}'",
            )


if __name__ == "__main__":
    unittest.main()
