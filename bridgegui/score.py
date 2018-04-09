"""Score widgets for bridge frontend

Thi module contains widgets for displaying scoresheet.

Classes:
ScoreTable -- table for displaying scoresheet
"""

from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem

import bridgegui.messaging as messaging
import bridgegui.positions as positions

SCORE_TAG = "score"
PARTNERSHIP_TAG = "partnership"


class ScoreTable(QTableWidget):
    """Table displaying scoresheet"""

    def __init__(self, parent=None):
        """Inititalize score table

        Keyword Arguments:
        parent -- the parent widget
        """
        super().__init__(0, len(positions.Partnership), parent)
        self.setHorizontalHeaderLabels(
            positions.partnershipLabel(partnership) for
            partnership in positions.Partnership)
        self.setMinimumWidth(
            5 + self.verticalHeader().width() +
            sum(self.columnWidth(n) for n in range(self.columnCount())))

    def addScore(self, score):
        """Add new score

        Adds new score to the scoresheet. The score is an object containing the
        partnership and amount of score awarded (see protocol specification). It
        may be None, in which case passed out deal is assumed.
        """
        new_score = self._generate_score_tuple(score)
        rows = self.rowCount()
        self.setRowCount(rows + 1)
        for col, amount in enumerate(new_score):
            self.setItem(rows, col, QTableWidgetItem(amount))

    def _generate_score_tuple(self, score):
        if score is None:
            return ("0", "0")
        try:
            amount = str(score[SCORE_TAG])
            winner = positions.asPartnership(score[PARTNERSHIP_TAG])
            if winner == positions.Partnership.northSouth:
                return (amount, "0")
            else:
                return ("0", amount)
        except Exception:
            raise messaging.ProtocolError("Invalid score: %r" % score)
