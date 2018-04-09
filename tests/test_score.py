import unittest
import sys

from PyQt5.QtWidgets import QApplication

import bridgegui.messaging as messaging
import bridgegui.positions as positions
import bridgegui.score as score

SCORESHEET = [
    None,
    dict(partnership=positions.NORTH_SOUTH_TAG, score=100),
    dict(partnership=positions.EAST_WEST_TAG, score=200),
]

SCORE_ITEMS = [
    ("0", "0"),
    ("100", "0"),
    ("0", "200"),
]


class ScoreTableTest(unittest.TestCase):
    """Test suite for scoresheet"""

    def setUp(self):
        self._app = QApplication(sys.argv)
        self._score_table = score.ScoreTable()

    def tearDown(self):
        del self._app

    def testAddScore(self):
        for score in SCORESHEET:
            self._score_table.addScore(score)
        for row, row_item in enumerate(SCORE_ITEMS):
            for col, item in enumerate(row_item):
                self.assertEqual(self._score_table.item(row, col).text(), item)

    def testAddScoreInvalid(self):
        with self.assertRaises(messaging.ProtocolError):
            self._score_table.addScore('invalid')
