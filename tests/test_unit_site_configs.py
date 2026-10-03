"""Unit tests for site configurations module (Scripts/Clawler/site_configs.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "Scripts/Clawler"))

from site_configs import build_run_configs


class TestSiteConfigsModule(unittest.TestCase):
    """Test domain selector configurations in site_configs.py."""

    def setUp(self):
        self.run_config, self.domain_configs = build_run_configs()

    def test_existing_domains_preserved(self):
        """Ensure critical existing domains are preserved."""
        baseline_domains = [
            "bachmai.gov.vn",
            "120ask.com",
            "cnkang.com",
            "wujue.com",
            "suckhoedoisong.vn",
            "dantri.com.vn",
            "thanhnien.vn",
            "vinmec.com",
            "nhathuoclongchau.com.vn",
        ]
        for domain in baseline_domains:
            with self.subTest(domain=domain):
                self.assertIn(domain, self.domain_configs)

    def test_newly_added_domains_configured(self):
        """Ensure new Chinese MediaWiki domains are configured properly."""
        new_domains = ["a-hospital.com", "zhongyibaodian.net"]
        for domain in new_domains:
            with self.subTest(domain=domain):
                self.assertIn(domain, self.domain_configs, f"{domain} should be configured in site_configs")
                cfg = self.domain_configs[domain]
                # Target elements should include firstHeading and bodyContent
                targets = getattr(cfg, "target_elements", []) or []
                self.assertTrue(
                    any("firstHeading" in t for t in targets),
                    f"{domain} target_elements missing firstHeading: {targets}"
                )
                self.assertTrue(
                    any("bodyContent" in t for t in targets),
                    f"{domain} target_elements missing bodyContent: {targets}"
                )


if __name__ == "__main__":
    unittest.main()
