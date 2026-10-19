"""Guard layer-shell reservation ordering, omitted by offscreen QML tests.

The Table must resize below the Top-layer bar, without shortening that bar.
"""

import re
import unittest
from pathlib import Path


class TableLayerTests(unittest.TestCase):
    def test_table_reserves_space_after_the_shell_bar_layer(self):
        source = (Path(__file__).resolve().parents[1] / "Panel.qml").read_text()
        table = source.split('objectName: "tableWindow"', 1)[1].split("ScaledViewport {", 1)[0]
        self.assertRegex(table, r"WlrLayershell\.layer:\s*WlrLayer\.Overlay\b")
        self.assertRegex(table, r"exclusionMode:\s*ExclusionMode\.Auto\b")
        self.assertRegex(table, r"implicitWidth:\s*Style\.space\(340\)\s*\*\s*root\.tableScale")
        self.assertEqual(set(re.findall(r"(top|right|bottom|left):\s*true", table)), {"top", "right", "bottom"})
