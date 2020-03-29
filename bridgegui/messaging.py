"""Messaging utilities for the bridge frontend"""

import re
import logging

import json
import zmq

EMPTY_FRAME = b''
REPLY_SUCCESS_PREFIX = [EMPTY_FRAME, b'success']

ENDPOINT_REGEX = re.compile(r"tcp://(.+):(\d+)")


def _failed_status_code(code):
    return code[:2] != b'OK'


def endpoints(base):
    """Generate successive endpoints starting from given base

    This generator consumes a base endpoint as its only argument. Each element
    is generated by keeping the address of the endpoint and increasing the port
    number by one.
    """
    match = ENDPOINT_REGEX.match(base)
    address = match.group(1)
    port = int(match.group(2))
    while True:
        yield "tcp://%s:%d" % (address, port)
        port += 1


def setupCurve(socket, serverKey):
    """Setup socket as curve client

    This function sets the options on the socket to make it act as CURVE
    client. Note that the client key is the test key documented in ZeroMQ manual
    and thus not suitable for actual authentication.

    Keyword Arguments:
    socket -- the ZeroMQ socket
    serverKey -- the public key of the server to be connected to

    """
    if not serverKey:
        return
    socket.curve_serverkey = serverKey.encode() + b'\0'
    socket.curve_publickey = b"Yne@$w-vo<fVvi]a<NY6T1ed:M$fCG*[IaLV{hID\0"
    socket.curve_secretkey = b"D:)Q[IlAW!ahhC2ac:9*A}h:p?([4%wOTJ%JR%cs\0"



def sendCommand(socket, command, _tag=None, **kwargs):
    """Send command to the backend application using the bridge protocol

    Keyword Arguments:
    socket   -- the socket used for sending the command
    command  -- (bytes) the command to be sent (also used as tag unless _tag is given)
    _tag     -- (bytes) the tag to be sent (overrides the default)
    **kwargs -- The arguments of the command (the values are serialized as JSON)
    """
    parts = [b'', _tag or command, command]
    for (key, value) in kwargs.items():
        parts.extend((key.encode(), json.dumps(value).encode()))
    logging.debug("Sending command: %r", parts)
    try:
        socket.send_multipart(parts)
    except zmq.ZMQError as e:
        logging.error(
            "Error %d while sending message %r: %s", e.errno, parts, str(e))


def validateControlReply(parts):
    """Validate control message reply

    The function checks if the parts given as argument contain one
    empty frame and successful status code. If yes, the command frame
    and the argument frames are returned as tuple. Otherwise (None,
    None) is returned.

    Keyword Arguments:
    parts -- the message frames (list of bytes)

    """
    if (len(parts) < 3 or parts[0] != EMPTY_FRAME or
        _failed_status_code(parts[2])):
        return None, None
    return parts[1], parts[3:]


def validateEventMessage(parts):
    """Validate event message

    This function just returns its arguments as is (there is nothing to validate
    about event message).
    """
    return parts[0], parts[1:]


class ProtocolError(Exception):
    """Error indicating unexpected message from bridge server"""
    pass


class MessageQueue:
    """Object for handling messages coming from the bridge server"""

    def __init__(self, socket, name, validator, handlers):
        """Initialize message queue

        Message queue keeps a reference to the given socket and wraps it into a
        QSocketNotifier to whose signals it connects to.

        Message handlers are provided as an argument to the initialized. The
        mapping is between commands (bytes) to handler functions. The handlers
        must accept the command parameters as keyword arguments. See bridge
        protocol specification for more information about the command and
        argument concepts.

        When message is received, it is first validated using the validator
        given as argument. Replies to control messages can be validated using
        validateControlReply and events can be validated using the (trivial)
        validateEventMessage.

        Keyword Arguments:
        socket    -- the ZMQ socket the message queue is backed by
        name      -- the name of the queue (for logging)
        validator -- Function for validating successful message
        handlers  -- mapping between commands and message handlers
        """
        self._socket = socket
        self._name = str(name)
        self._validator = validator
        self._handlers = dict(handlers)

    def handleMessages(self):
        """Notify the message queue that messages can be handled

        The message queue handles messages from its socket until there are no
        messages to receive or handling of a message results in an error. If
        handling messages stops due to an error, False is returned. Otherwise
        True is returned.
        """
        ret = True
        while self._socket.events & zmq.POLLIN:
            try:
                parts = self._socket.recv_multipart()
            except zmq.ContextTerminated: # It's okay as we're about to exit
                return True
            except zmq.ZMQError as e:
                logging.error(
                    "Error %d while receiving message from %s: %s",
                    e.errno, self._name, str(e))
                ret = False
            else:
                try:
                    self._handle_message(parts)
                except ProtocolError as e:
                    logging.warning(
                        "Unexpected event while handling message %r from %s: %s",
                        parts, self._name, str(e))
                    ret = False
        return ret

    def _handle_message(self, parts):
        logging.debug("Received message: %r", parts)
        command, parts = self._validator(parts)
        if command is None or parts is None:
            raise ProtocolError("Invalid message parts: %r" % parts)
        command_handler = self._handlers.get(command, None)
        if not command_handler:
            raise ProtocolError("Unrecognized command: %r" % command)
        if len(parts) % 2 != 0:
            raise ProtocolError(
                "Expecting even number of parameter frames, got: %r" % parts)
        kwargs = {}
        for n in range(0, len(parts), 2):
            key = parts[n].decode()
            value = parts[n+1].decode()
            try:
                value = json.loads(value)
            except json.decoder.JSONDecodeError as e:
                raise ProtocolError("Error while parsing %r: %r" % (value, e))
            kwargs[key] = value
        command_handler(**kwargs)
