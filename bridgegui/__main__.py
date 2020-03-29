"""Bridge frontend

This module contains the startpoint for the frontend which is part of the bridge
project. The usage is documented when the script is run with the -h argument.
"""

import argparse
import json
import logging
import re
import sys

from PyQt5.QtCore import QSocketNotifier, QTimer
from PyQt5.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QMessageBox, QVBoxLayout, QWidget)
import zmq

import bridgegui.bidding as bidding
import bridgegui.cards as cards
import bridgegui.config as config
import bridgegui.messaging as messaging
from bridgegui.messaging import sendCommand
from bridgegui.positions import POSITION_TAGS
import bridgegui.score as score
import bridgegui.tricks as tricks

HELLO_COMMAND = b'bridgehlo'
GAME_COMMAND = b'game'
JOIN_COMMAND = b'join'
INITGET_COMMAND = b'initget'
GET_COMMAND = b'get'
DEAL_COMMAND = b'deal'
CALL_COMMAND = b'call'
BIDDING_COMMAND = b'bidding'
PLAY_COMMAND = b'play'
TURN_COMMAND = b'turn'
DUMMY_COMMAND = b'dummy'
TRICK_COMMAND = b'trick'
DEALEND_COMMAND = b'dealend'

CLIENT_TAG = "client"
POSITION_TAG = "position"
GAME_TAG = "game"
PUBSTATE_TAG = "pubstate"
PRIVSTATE_TAG = "privstate"
SELF_TAG = "self"
POSITION_IN_TURN_TAG = "positionInTurn"
ALLOWED_CALLS_TAG = "allowedCalls"
CALLS_TAG = "calls"
DECLARER_TAG = "declarer"
CONTRACT_TAG = "contract"
ALLOWED_CARDS_TAG = "allowedCards"
CARDS_TAG = "cards"
TRICK_TAG = "trick"
TRICKS_WON_TAG = "tricksWon"
VULNERABILITY_TAG = "vulnerability"

class BridgeWindow(QMainWindow):
    """The main window of the birdge frontend"""

    def __init__(
            self, control_socket, event_socket, position, game_uuid,
            create_game):
        """Initialize BridgeWindow

        Keyword Arguments:
        control_socket -- the control socket used to send commands
        event_socket   -- the event socket used to subscribe events
        position       -- the preferred position
        game_uuid      -- the UUID of the game to be joined (optional)
        create_game    -- flag indicating whether the client should create a new game
        """
        super().__init__()
        self._position = None
        self._preferred_position = position
        self._game_uuid = game_uuid
        self._create_game = create_game
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._init_sockets(control_socket, event_socket)
        self._init_widgets()
        self.setWindowTitle("Bridge") # TODO: Localization
        self.show()
        self._timer.start()

    def _init_sockets(self, control_socket, event_socket):
        logging.info("Initializing message handlers")
        zmqctx = zmq.Context.instance()
        self._socket_notifiers = []
        self._control_socket = control_socket
        self._control_socket_queue = messaging.MessageQueue(
            control_socket, "control socket queue",
            messaging.validateControlReply,
            {
                HELLO_COMMAND: self._handle_hello_reply,
                GAME_COMMAND: self._handle_game_reply,
                JOIN_COMMAND: self._handle_join_reply,
                INITGET_COMMAND: self._handle_init_get_reply,
                GET_COMMAND: self._handle_get_reply,
                CALL_COMMAND: self._handle_call_reply,
                PLAY_COMMAND: self._handle_play_reply,
            })
        self._connect_socket_to_notifier(
            control_socket, self._control_socket_queue)
        self._event_socket = event_socket
        sendCommand(control_socket, HELLO_COMMAND, version="0.1", role=CLIENT_TAG)

    def _init_widgets(self):
        logging.info("Initializing widgets")
        self._central_widget = QWidget(self)
        self._layout = QHBoxLayout(self._central_widget)
        self._bidding_layout = QVBoxLayout()
        self._call_panel = bidding.CallPanel(self._central_widget)
        self._call_panel.callMade.connect(self._send_call_command)
        self._bidding_layout.addWidget(self._call_panel)
        self._call_table = bidding.CallTable(self._central_widget)
        self._bidding_layout.addWidget(self._call_table)
        self._bidding_result_label = bidding.ResultLabel(self._central_widget)
        self._bidding_layout.addWidget(self._bidding_result_label)
        self._tricks_won_label = tricks.TricksWonLabel(self._central_widget)
        self._bidding_layout.addWidget(self._tricks_won_label)
        self._layout.addLayout(self._bidding_layout)
        self._card_area = cards.CardArea(self._central_widget)
        for hand in self._card_area.hands():
            hand.cardPlayed.connect(self._send_play_command)
        self._layout.addWidget(self._card_area)
        self._score_table = score.ScoreTable(self._central_widget)
        self._layout.addWidget(self._score_table)
        self.setCentralWidget(self._central_widget)
        self._counter = None

    def _is_stale_event(self, counter):
        if not counter:
            return False
        elif self._counter and self._counter > counter:
            logging.debug(
                "Stale event, counter: %r, self._counter %r",
                counter, self._counter)
            return True
        else:
            return False

    def _get_event_type(self, name):
        return self._game_uuid.encode() + b':' + name

    def _init_game(self, game_uuid):
        self._game_uuid = game_uuid
        self._event_socket.setsockopt(zmq.SUBSCRIBE, game_uuid.encode())
        self._event_socket_queue = messaging.MessageQueue(
            self._event_socket, "event socket queue", messaging.validateEventMessage,
            {
                self._get_event_type(DEAL_COMMAND): self._handle_deal_event,
                self._get_event_type(TURN_COMMAND): self._handle_turn_event,
                self._get_event_type(CALL_COMMAND): self._handle_call_event,
                self._get_event_type(BIDDING_COMMAND): self._handle_bidding_event,
                self._get_event_type(PLAY_COMMAND): self._handle_play_event,
                self._get_event_type(DUMMY_COMMAND): self._handle_dummy_event,
                self._get_event_type(TRICK_COMMAND): self._handle_trick_event,
                self._get_event_type(DEALEND_COMMAND): self._handle_dealend_event,
            })

    def _start_handling_events(self):
        self._connect_socket_to_notifier(
            self._event_socket, self._event_socket_queue)

    def _connect_socket_to_notifier(self, socket, message_queue):
        def _handle_message_to_queue():
            if not message_queue.handleMessages():
                # TODO: Localization
                QMessageBox.warning(
                    self, "Server error",
                    "Error while receiving message from server. Please see logs.")
                self._timer.timeout.disconnect(_handle_message_to_queue)
        socket_notifier = QSocketNotifier(socket.fd, QSocketNotifier.Read, self)
        socket_notifier.activated.connect(_handle_message_to_queue)
        self._timer.timeout.connect(_handle_message_to_queue)
        self._socket_notifiers.append(socket_notifier)

    def _request(self, *args):
        sendCommand(
            self._control_socket, GET_COMMAND, game=self._game_uuid, get=args)

    def _send_join_command(self):
        kwargs = {}
        if self._preferred_position:
            kwargs[POSITION_TAG] = self._preferred_position
        if self._game_uuid:
            kwargs[GAME_TAG] = self._game_uuid
        sendCommand(self._control_socket, JOIN_COMMAND, **kwargs)

    def _send_call_command(self, call):
        sendCommand(
            self._control_socket, CALL_COMMAND, game=self._game_uuid, call=call)

    def _send_play_command(self, card):
        sendCommand(
            self._control_socket, PLAY_COMMAND, game=self._game_uuid,
            card=card._asdict())

    def _handle_hello_reply(self, **kwargs):
        logging.info("Handshake successful")
        if self._create_game:
            kwargs = { 'game': self._game_uuid } if self._game_uuid else {}
            sendCommand(self._control_socket, GAME_COMMAND, **kwargs)
        else:
            self._send_join_command()

    def _handle_game_reply(self, game=None, **kwargs):
        logging.info("Created game %r", game)
        self._game_uuid = game
        self._send_join_command()

    def _handle_join_reply(self, game=None, **kwargs):
        logging.info("Joined game %r", game)
        if game:
            self._init_game(game)
            sendCommand(self._control_socket, GET_COMMAND, INITGET_COMMAND, game=game)
        else:
            logging.error("Unable to join game")

    def _handle_init_get_reply(self, get=None, counter=None, **kwargs):
        self._handle_get_reply(get, counter, **kwargs)
        self._start_handling_events()

    def _handle_get_reply(self, get=None, counter=None, **kwargs):
        if counter:
            self._counter = counter
        else:
            logging.warning("No counter included in get reply")
        missing = object()
        pubstate = get.get(PUBSTATE_TAG, {})
        privstate = get.get(PRIVSTATE_TAG, {})
        _self = get.get(SELF_TAG, {})
        position = _self.get(POSITION_TAG, missing)
        if position is not missing and position != self._position:
            self._position = position
            self._card_area.setPlayerPosition(position)
        position_in_turn = _self.get(POSITION_IN_TURN_TAG, missing)
        if position_in_turn is not missing:
            self._card_area.setPositionInTurn(position_in_turn)
        allowed_calls = _self.get(ALLOWED_CALLS_TAG, missing)
        if allowed_calls is not missing:
            self._call_panel.setAllowedCalls(allowed_calls)
        calls = pubstate.get(CALLS_TAG, missing)
        if calls is not missing:
            self._call_table.setCalls(calls)
        declarer = pubstate.get(DECLARER_TAG, missing)
        contract = pubstate.get(CONTRACT_TAG, missing)
        if declarer is not missing and contract is not missing:
            self._bidding_result_label.setBiddingResult(
                declarer, contract)
        cards = pubstate.get(CARDS_TAG, {})
        cards.update(privstate.get(CARDS_TAG, {}))
        if cards:
            self._card_area.setCards(cards)
        allowed_cards = _self.get(ALLOWED_CARDS_TAG, missing)
        if allowed_cards is not missing:
            self._card_area.setAllowedCards(allowed_cards)
        trick = pubstate.get(TRICK_TAG, missing)
        if trick is not missing:
            self._card_area.setTrick(trick)
        tricks_won = pubstate.get(TRICKS_WON_TAG, missing)
        if tricks_won is not missing:
            self._tricks_won_label.setTricksWon(tricks_won)
        vulnerability = pubstate.get(VULNERABILITY_TAG, missing)
        if vulnerability is not missing:
            self._call_table.setVulnerability(vulnerability)

    def _handle_call_reply(self, **kwargs):
        logging.debug("Call successful")

    def _handle_play_reply(self, **kwargs):
        logging.debug("Play successful")

    def _handle_deal_event(
            self, opener=None, vulnerability=None, counter=None, **kwargs):
        if self._is_stale_event(counter):
            return
        logging.debug("Cards dealt")
        self._card_area.setPositionInTurn(opener)
        self._call_table.setVulnerability(vulnerability)
        self._bidding_result_label.setBiddingResult(None, None)
        self._request(PUBSTATE_TAG, PRIVSTATE_TAG)

    def _handle_turn_event(self, position=None, counter=None, **kwargs):
        if self._is_stale_event(counter):
            return
        logging.debug("Position in turn: %r", position)
        self._card_area.setPositionInTurn(position)
        if position == self._position:
            self._request(SELF_TAG)
        else:
            self._call_panel.setAllowedCalls([])
            self._card_area.setAllowedCards([])

    def _handle_call_event(
            self, position=None, call=None, counter=None, **kwargs):
        if self._is_stale_event(counter):
            return
        logging.debug("Call made. Position: %r, Call: %r", position, call)
        self._call_table.addCall(position, call)

    def _handle_bidding_event(
            self, declarer=None, contract=None, counter=None, **kwargs):
        if self._is_stale_event(counter):
            return
        logging.debug(
            "Bidding completed. Declarer: %r, Contract: %r", declarer, contract)
        self._bidding_result_label.setBiddingResult(declarer, contract)

    def _handle_play_event(
            self, position=None, card=None, counter=None, **kwargs):
        if self._is_stale_event(counter):
            return
        logging.debug("Card played. Position: %r, Card: %r", position, card)
        self._card_area.playCard(position, card)

    def _handle_dummy_event(
            self, counter=None, position=None, cards=None, **kwargs):
        if self._is_stale_event(counter):
            return
        logging.debug("Dummy hand revealed")
        self._card_area.setCards({ position: cards })

    def _handle_trick_event(self, winner, counter=None, **kwargs):
        if self._is_stale_event(counter):
            return
        logging.debug("Trick completed. Winner: %r", winner)
        self._tricks_won_label.addTrick(winner)

    def _handle_dealend_event(
            self, tricksWon=None, score=None, counter=None, **kwargs):
        if self._is_stale_event(counter):
            return
        logging.debug("Deal ended. Tricks won: %r. Score: %r", tricksWon, score)
        self._score_table.addScore(score)
        self._call_table.setCalls([])
        self._tricks_won_label.setTricksWon(tricksWon)

def main():
    parser = argparse.ArgumentParser(
        description="A lightweight bridge application")
    parser.add_argument(
        "endpoint",
        help="""Base endpoint of the bridge backend. Follows ZeroMQ transmit
             protocol syntax. For example: tcp://bridge.example.com:5555""")
    parser.add_argument(
        "--server-key-file",
        help="""File to read CURVE server key from. If provided, the sockets are
             setup to use CURVE security mechanism with the given server
             key.""",
        type=argparse.FileType("r")
    )
    parser.add_argument(
        "--config",
        help="""Configuration file. The file tracks the identity of the player
             withing a single bridge session. By using the same configuration
             file between runs, the game session can be preserved.

             If the file does not exist, it will be created with a new random
             identity. It is possible to play without config file but in that
             case preserving the session is not possible.""")
    parser.add_argument(
        '--position',
        help="""If provided, the application requests the server to assign the
             given position. If the position is not available (or if the option
             is not given), any position is requested.""")
    parser.add_argument(
        '--game',
        help="""UUID of the game to be joined. The game is not created unless
             --create-game option is also provided.""")
    parser.add_argument(
        '--create-game', action="store_true",
        help="""If given, the application requests the backend to create new
             game. UUID can be optionally given by providing --game option.""")
    parser.add_argument(
        "--verbose", "-v", action="count", default=0,
        help="""Increase logging levels. Repeat for even more logging.""")
    args = parser.parse_args()

    logging_level = logging.WARNING
    if args.verbose == 1:
        logging_level = logging.INFO
    elif args.verbose >= 2:
        logging_level = logging.DEBUG
    logging.basicConfig(
        format='%(asctime)s %(levelname)-8s %(message)s', level=logging_level)

    logging.info("Initializing sockets")
    zmqctx = zmq.Context.instance()
    endpoint_generator = messaging.endpoints(args.endpoint)
    control_socket = zmqctx.socket(zmq.DEALER)
    identity = config.getIdentity(args.config)
    control_socket.identity = identity.bytes
    if args.server_key_file:
        with args.server_key_file:
            curve_server_key = args.server_key_file.readline().strip()
    else:
        curve_server_key = None
    messaging.setupCurve(control_socket, curve_server_key)
    control_socket.connect(next(endpoint_generator))
    event_socket = zmqctx.socket(zmq.SUB)
    messaging.setupCurve(event_socket, curve_server_key)
    event_socket.connect(next(endpoint_generator))

    logging.info("Starting main window")
    app = QApplication(sys.argv)
    window = BridgeWindow(
        control_socket, event_socket, args.position, args.game,
        args.create_game)
    code = app.exec_()

    logging.info("Main window closed. Closing sockets.")
    zmqctx.destroy(linger=0)
    return code


if __name__ == "__main__":
    main()
